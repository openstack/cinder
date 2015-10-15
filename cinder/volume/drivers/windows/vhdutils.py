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

VHD related Win32 API reference:
http://msdn.microsoft.com/en-us/library/windows/desktop/dd323700.aspx
"""
import ctypes
import os
import sys

if os.name == 'nt':
    from ctypes import wintypes
    kernel32 = ctypes.windll.kernel32
    virtdisk = ctypes.windll.virtdisk

from oslo_log import log as logging

from cinder import exception
from cinder.i18n import _
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
            ('DeviceId', wintypes.ULONG),
            ('VendorId', Win32_GUID)
        ]

    class Win32_RESIZE_VIRTUAL_DISK_PARAMETERS(ctypes.Structure):
        _fields_ = [
            ('Version', wintypes.DWORD),
            ('NewSize', ctypes.c_ulonglong)
        ]

    class Win32_OPEN_VIRTUAL_DISK_PARAMETERS_V1(ctypes.Structure):
        _fields_ = [
            ('Version', wintypes.DWORD),
            ('RWDepth', ctypes.c_ulong),
        ]

    class Win32_OPEN_VIRTUAL_DISK_PARAMETERS_V2(ctypes.Structure):
        _fields_ = [
            ('Version', wintypes.DWORD),
            ('GetInfoOnly', wintypes.BOOL),
            ('ReadOnly', wintypes.BOOL),
            ('ResiliencyGuid', Win32_GUID)
        ]

    class Win32_MERGE_VIRTUAL_DISK_PARAMETERS(ctypes.Structure):
        _fields_ = [
            ('Version', wintypes.DWORD),
            ('MergeDepth', ctypes.c_ulong)
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

    class Win32_SIZE(ctypes.Structure):
        _fields_ = [("VirtualSize", wintypes.ULARGE_INTEGER),
                    ("PhysicalSize", wintypes.ULARGE_INTEGER),
                    ("BlockSize", wintypes.ULONG),
                    ("SectorSize", wintypes.ULONG)]

    class Win32_PARENT_LOCATION(ctypes.Structure):
        _fields_ = [('ParentResolved', wintypes.BOOL),
                    ('ParentLocationBuffer', wintypes.WCHAR * 512)]

    class Win32_PHYSICAL_DISK(ctypes.Structure):
        _fields_ = [("LogicalSectorSize", wintypes.ULONG),
                    ("PhysicalSectorSize", wintypes.ULONG),
                    ("IsRemote", wintypes.BOOL)]

    class Win32_VHD_INFO(ctypes.Union):
        _fields_ = [("Size", Win32_SIZE),
                    ("Identifier", Win32_GUID),
                    ("ParentLocation", Win32_PARENT_LOCATION),
                    ("ParentIdentifier", Win32_GUID),
                    ("ParentTimestamp", wintypes.ULONG),
                    ("VirtualStorageType", Win32_VIRTUAL_STORAGE_TYPE),
                    ("ProviderSubtype", wintypes.ULONG),
                    ("Is4kAligned", wintypes.BOOL),
                    ("PhysicalDisk", Win32_PHYSICAL_DISK),
                    ("VhdPhysicalSectorSize", wintypes.ULONG),
                    ("SmallestSafeVirtualSize",
                        wintypes.ULARGE_INTEGER),
                    ("FragmentationPercentage", wintypes.ULONG)]

    class Win32_GET_VIRTUAL_DISK_INFO_PARAMETERS(ctypes.Structure):
        _fields_ = [("VERSION", wintypes.UINT),
                    ("VhdInfo", Win32_VHD_INFO)]

    class Win32_SET_VIRTUAL_DISK_INFO_PARAMETERS(ctypes.Structure):
        _fields_ = [
            ('Version', wintypes.DWORD),
            ('ParentFilePath', wintypes.LPCWSTR)
        ]


VIRTUAL_STORAGE_TYPE_DEVICE_ISO = 1
VIRTUAL_STORAGE_TYPE_DEVICE_VHD = 2
VIRTUAL_STORAGE_TYPE_DEVICE_VHDX = 3
VIRTUAL_DISK_ACCESS_NONE = 0
VIRTUAL_DISK_ACCESS_ALL = 0x003f0000
VIRTUAL_DISK_ACCESS_CREATE = 0x00100000
VIRTUAL_DISK_ACCESS_GET_INFO = 0x80000
OPEN_VIRTUAL_DISK_FLAG_NONE = 0
OPEN_VIRTUAL_DISK_FLAG_NO_PARENTS = 1
OPEN_VIRTUAL_DISK_VERSION_1 = 1
OPEN_VIRTUAL_DISK_VERSION_2 = 2
RESIZE_VIRTUAL_DISK_FLAG_NONE = 0
RESIZE_VIRTUAL_DISK_VERSION_1 = 1
CREATE_VIRTUAL_DISK_VERSION_2 = 2
CREATE_VHD_PARAMS_DEFAULT_BLOCK_SIZE = 0
CREATE_VIRTUAL_DISK_FLAG_NONE = 0
CREATE_VIRTUAL_DISK_FLAG_FULL_PHYSICAL_ALLOCATION = 1
MERGE_VIRTUAL_DISK_VERSION_1 = 1
MERGE_VIRTUAL_DISK_FLAG_NONE = 0x00000000
GET_VIRTUAL_DISK_INFO_SIZE = 1
GET_VIRTUAL_DISK_INFO_PARENT_LOCATION = 3
GET_VIRTUAL_DISK_INFO_VIRTUAL_STORAGE_TYPE = 6
GET_VIRTUAL_DISK_INFO_PROVIDER_SUBTYPE = 7
SET_VIRTUAL_DISK_INFO_PARENT_PATH = 1

FORMAT_MESSAGE_FROM_SYSTEM = 0x00001000
FORMAT_MESSAGE_ALLOCATE_BUFFER = 0x00000100
FORMAT_MESSAGE_IGNORE_INSERTS = 0x00000200

ERROR_VHD_INVALID_TYPE = 0xC03A001B


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
        self._vhd_info_members = {
            GET_VIRTUAL_DISK_INFO_SIZE: 'Size',
            GET_VIRTUAL_DISK_INFO_PARENT_LOCATION: 'ParentLocation',
            GET_VIRTUAL_DISK_INFO_VIRTUAL_STORAGE_TYPE:
                'VirtualStorageType',
            GET_VIRTUAL_DISK_INFO_PROVIDER_SUBTYPE: 'ProviderSubtype',
        }

        if os.name == 'nt':
            self._msft_vendor_id = (
                self.get_WIN32_VIRTUAL_STORAGE_TYPE_VENDOR_MSFT())

    def _run_and_check_output(self, func, *args, **kwargs):
        """Convenience helper method for running Win32 API methods."""
        ignored_error_codes = kwargs.pop('ignored_error_codes', [])

        ret_val = func(*args, **kwargs)

        # The VHD Win32 API functions return non-zero error codes
        # in case of failure.
        if ret_val and ret_val not in ignored_error_codes:
            error_message = self._get_error_message(ret_val)
            func_name = getattr(func, '__name__', '')
            err = (_("Executing Win32 API function %(func_name)s failed. "
                     "Error code: %(error_code)s. "
                     "Error message: %(error_message)s") %
                   {'func_name': func_name,
                    'error_code': ret_val,
                    'error_message': error_message})
            LOG.error(err, exc_info=(sys.exc_info() is not None))
            raise exception.VolumeBackendAPIException(err)

    @staticmethod
    def _get_error_message(error_code):
        message_buffer = ctypes.c_char_p()

        kernel32.FormatMessageA(
            FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_ALLOCATE_BUFFER |
            FORMAT_MESSAGE_IGNORE_INSERTS,
            None, error_code, 0, ctypes.byref(message_buffer), 0, None)

        error_message = message_buffer.value
        kernel32.LocalFree(message_buffer)
        return error_message

    @staticmethod
    def get_WIN32_VIRTUAL_STORAGE_TYPE_VENDOR_MSFT():
        guid = Win32_GUID()
        guid.Data1 = 0xec984aec
        guid.Data2 = 0xa0f9
        guid.Data3 = 0x47e9
        ByteArray8 = wintypes.BYTE * 8
        guid.Data4 = ByteArray8(0x90, 0x1f, 0x71, 0x41, 0x5a, 0x66, 0x34, 0x5b)
        return guid

    def _open(self, vhd_path, open_flag=OPEN_VIRTUAL_DISK_FLAG_NONE,
              open_access_mask=VIRTUAL_DISK_ACCESS_ALL,
              open_params=0):
        device_id = self._get_device_id_by_path(vhd_path)

        vst = Win32_VIRTUAL_STORAGE_TYPE()
        vst.DeviceId = device_id
        vst.VendorId = self._msft_vendor_id

        handle = wintypes.HANDLE()

        self._run_and_check_output(virtdisk.OpenVirtualDisk,
                                   ctypes.byref(vst),
                                   ctypes.c_wchar_p(vhd_path),
                                   open_access_mask,
                                   open_flag,
                                   open_params,
                                   ctypes.byref(handle))
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
        handle = self._open(vhd_path)

        params = Win32_RESIZE_VIRTUAL_DISK_PARAMETERS()
        params.Version = RESIZE_VIRTUAL_DISK_VERSION_1
        params.NewSize = new_max_size

        try:
            self._run_and_check_output(virtdisk.ResizeVirtualDisk,
                                       handle,
                                       RESIZE_VIRTUAL_DISK_FLAG_NONE,
                                       ctypes.byref(params),
                                       None)
        finally:
            self._close(handle)

    def merge_vhd(self, vhd_path):
        open_params = Win32_OPEN_VIRTUAL_DISK_PARAMETERS_V1()
        open_params.Version = OPEN_VIRTUAL_DISK_VERSION_1
        open_params.RWDepth = 2

        handle = self._open(vhd_path,
                            open_params=ctypes.byref(open_params))

        params = Win32_MERGE_VIRTUAL_DISK_PARAMETERS()
        params.Version = MERGE_VIRTUAL_DISK_VERSION_1
        params.MergeDepth = 1

        try:
            self._run_and_check_output(virtdisk.MergeVirtualDisk,
                                       handle,
                                       MERGE_VIRTUAL_DISK_FLAG_NONE,
                                       ctypes.byref(params),
                                       None)
        finally:
            self._close(handle)

    def _create_vhd(self, new_vhd_path, new_vhd_type, src_path=None,
                    max_internal_size=0, parent_path=None):
        new_device_id = self._get_device_id_by_path(new_vhd_path)

        vst = Win32_VIRTUAL_STORAGE_TYPE()
        vst.DeviceId = new_device_id
        vst.VendorId = self._msft_vendor_id

        params = Win32_CREATE_VIRTUAL_DISK_PARAMETERS()
        params.Version = CREATE_VIRTUAL_DISK_VERSION_2
        params.UniqueId = Win32_GUID()
        params.BlockSizeInBytes = CREATE_VHD_PARAMS_DEFAULT_BLOCK_SIZE
        params.SectorSizeInBytes = 0x200
        params.PhysicalSectorSizeInBytes = 0x200
        params.OpenFlags = OPEN_VIRTUAL_DISK_FLAG_NONE
        params.ResiliencyGuid = Win32_GUID()
        params.MaximumSize = max_internal_size
        params.ParentPath = parent_path
        params.ParentVirtualStorageType = Win32_VIRTUAL_STORAGE_TYPE()

        if src_path:
            src_device_id = self._get_device_id_by_path(src_path)
            params.SourcePath = src_path
            params.SourceVirtualStorageType = Win32_VIRTUAL_STORAGE_TYPE()
            params.SourceVirtualStorageType.DeviceId = src_device_id
            params.SourceVirtualStorageType.VendorId = self._msft_vendor_id

        handle = wintypes.HANDLE()
        create_virtual_disk_flag = self.create_virtual_disk_flags.get(
            new_vhd_type)

        try:
            self._run_and_check_output(virtdisk.CreateVirtualDisk,
                                       ctypes.byref(vst),
                                       ctypes.c_wchar_p(new_vhd_path),
                                       VIRTUAL_DISK_ACCESS_NONE,
                                       None,
                                       create_virtual_disk_flag,
                                       0,
                                       ctypes.byref(params),
                                       None,
                                       ctypes.byref(handle))
        finally:
            self._close(handle)

    def get_vhd_info(self, vhd_path, info_members=None):
        vhd_info = {}
        info_members = info_members or self._vhd_info_members

        handle = self._open(vhd_path,
                            open_access_mask=VIRTUAL_DISK_ACCESS_GET_INFO)

        try:
            for member in info_members:
                info = self._get_vhd_info_member(handle, member)
                vhd_info.update(info)
        finally:
            self._close(handle)

        return vhd_info

    def _get_vhd_info_member(self, vhd_file, info_member):
        virt_disk_info = Win32_GET_VIRTUAL_DISK_INFO_PARAMETERS()
        virt_disk_info.VERSION = ctypes.c_uint(info_member)

        infoSize = ctypes.sizeof(virt_disk_info)

        virtdisk.GetVirtualDiskInformation.restype = wintypes.DWORD

        # Note(lpetrut): If the vhd has no parent image, this will
        # return an error. No need to raise an exception in this case.
        ignored_error_codes = []
        if info_member == GET_VIRTUAL_DISK_INFO_PARENT_LOCATION:
            ignored_error_codes.append(ERROR_VHD_INVALID_TYPE)

        self._run_and_check_output(virtdisk.GetVirtualDiskInformation,
                                   vhd_file,
                                   ctypes.byref(ctypes.c_ulong(infoSize)),
                                   ctypes.byref(virt_disk_info),
                                   0,
                                   ignored_error_codes=ignored_error_codes)

        return self._parse_vhd_info(virt_disk_info, info_member)

    def _parse_vhd_info(self, virt_disk_info, info_member):
        vhd_info = {}
        vhd_info_member = self._vhd_info_members[info_member]
        info = getattr(virt_disk_info.VhdInfo, vhd_info_member)

        if hasattr(info, '_fields_'):
            for field in info._fields_:
                vhd_info[field[0]] = getattr(info, field[0])
        else:
            vhd_info[vhd_info_member] = info

        return vhd_info

    def get_vhd_size(self, vhd_path):
        """Return vhd size.

        Returns a dict containing the virtual size, physical size,
        block size and sector size of the vhd.
        """
        size = self.get_vhd_info(vhd_path,
                                 [GET_VIRTUAL_DISK_INFO_SIZE])
        return size

    def get_vhd_parent_path(self, vhd_path):
        vhd_info = self.get_vhd_info(vhd_path,
                                     [GET_VIRTUAL_DISK_INFO_PARENT_LOCATION])
        parent_path = vhd_info['ParentLocationBuffer']

        if len(parent_path) > 0:
            return parent_path
        return None

    def create_dynamic_vhd(self, path, max_internal_size):
        self._create_vhd(path,
                         constants.VHD_TYPE_DYNAMIC,
                         max_internal_size=max_internal_size)

    def convert_vhd(self, src, dest,
                    vhd_type=constants.VHD_TYPE_DYNAMIC):
        self._create_vhd(dest, vhd_type, src_path=src)

    def create_differencing_vhd(self, path, parent_path):
        self._create_vhd(path,
                         constants.VHD_TYPE_DIFFERENCING,
                         parent_path=parent_path)

    def reconnect_parent(self, child_path, parent_path):
        open_params = Win32_OPEN_VIRTUAL_DISK_PARAMETERS_V2()
        open_params.Version = OPEN_VIRTUAL_DISK_VERSION_2
        open_params.GetInfoOnly = False

        handle = self._open(
            child_path,
            open_flag=OPEN_VIRTUAL_DISK_FLAG_NO_PARENTS,
            open_access_mask=VIRTUAL_DISK_ACCESS_NONE,
            open_params=ctypes.byref(open_params))

        params = Win32_SET_VIRTUAL_DISK_INFO_PARAMETERS()
        params.Version = SET_VIRTUAL_DISK_INFO_PARENT_PATH
        params.ParentFilePath = parent_path

        try:
            self._run_and_check_output(virtdisk.SetVirtualDiskInformation,
                                       handle,
                                       ctypes.byref(params))
        finally:
            self._close(handle)
