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
import os

if os.name == 'nt':
    import wmi

from cinder.openstack.common import log as logging
from cinder.volume.drivers.windows import windows_utils

LOG = logging.getLogger(__name__)


class VHDUtils(object):

    def __init__(self):
        self.utils = windows_utils.WindowsUtils()
        self._conn = wmi.WMI(moniker='//./root/virtualization')

    def convert_vhd(self, src, dest, vhd_type=None):
        image_man_svc = self._conn.Msvm_ImageManagementService()[0]
        (job_path, ret_val) = image_man_svc.ConvertVirtualHardDisk(
            SourcePath=src, DestinationPath=dest, Type=vhd_type)
        self.utils.check_ret_val(ret_val, job_path)

    def _get_resize_method(self):
        image_man_svc = self._conn.Msvm_ImageManagementService()[0]
        return image_man_svc.ExpandVirtualHardDisk

    def resize_vhd(self, vhd_path, new_max_size):
        resize = self._get_resize_method()
        (job_path, ret_val) = resize(Path=vhd_path,
                                     MaxInternalSize=new_max_size)
        self.utils.check_ret_val(ret_val, job_path)
