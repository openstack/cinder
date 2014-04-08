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
Based on the "root/virtualization/v2" namespace available starting with
Hyper-V Server / Windows Server 2012.
"""
import os

if os.name == 'nt':
    import wmi

from cinder.openstack.common import log as logging
from cinder.volume.drivers.windows import constants
from cinder.volume.drivers.windows import vhdutils
from cinder.volume.drivers.windows import windows_utils

LOG = logging.getLogger(__name__)


class VHDUtilsV2(vhdutils.VHDUtils):

    _vhd_format_map = {
        'vhd': 2,
        'vhdx': 3,
    }

    def __init__(self):
        self.utils = windows_utils.WindowsUtils()
        self._conn = wmi.WMI(moniker='//./root/virtualization/v2')

    def _get_resize_method(self):
        image_man_svc = self._conn.Msvm_ImageManagementService()[0]
        return image_man_svc.ResizeVirtualHardDisk

    def convert_vhd(self, src, dest, vhd_type=constants.VHD_TYPE_DYNAMIC):
        vhd_info = self._conn.Msvm_VirtualHardDiskSettingData.new()
        ext = os.path.splitext(dest)[1][1:]
        format = self._vhd_format_map.get(ext)

        vhd_info.Type = vhd_type
        vhd_info.Path = dest
        vhd_info.Format = format
        vhd_info.BlockSize = 0
        vhd_info.LogicalSectorSize = 0
        vhd_info.ParentPath = None

        image_man_svc = self._conn.Msvm_ImageManagementService()[0]
        (job_path, ret_val) = image_man_svc.ConvertVirtualHardDisk(
            SourcePath=src, VirtualDiskSettingData=vhd_info.GetText_(1))
        self.utils.check_ret_val(ret_val, job_path)
