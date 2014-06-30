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

from cinder import test
from cinder.volume.drivers.windows import vhdutils
from cinder.volume.drivers.windows import windows_utils


class VHDUtilsTestCase(test.TestCase):

    _FAKE_FORMAT = 2
    _FAKE_TYPE = 3
    _FAKE_JOB_PATH = 'fake_job_path'
    _FAKE_VHD_PATH = r'C:\fake\vhd.vhd'
    _FAKE_DESTINATION_PATH = r'C:\fake\destination.vhd'
    _FAKE_RET_VAL = 0
    _FAKE_VHD_SIZE = 1024

    def setUp(self):
        super(VHDUtilsTestCase, self).setUp()
        windows_utils.WindowsUtils.__init__ = lambda x: None
        vhdutils.VHDUtils.__init__ = lambda x: None
        self.wutils = windows_utils.WindowsUtils()
        self.wutils.check_ret_val = mock.MagicMock()
        self.vhdutils = vhdutils.VHDUtils()
        self.vhdutils._conn = mock.MagicMock()
        self.vhdutils.utils = self.wutils
        self.mock_img_svc = (
            self.vhdutils._conn.Msvm_ImageManagementService()[0])
        self.vhdutils._get_resize_method = mock.Mock(
            return_value=self.mock_img_svc.ExpandVirtualHardDisk)

    def test_convert_vhd(self):
        self.mock_img_svc.ConvertVirtualHardDisk.return_value = (
            self._FAKE_JOB_PATH, self._FAKE_RET_VAL)

        self.vhdutils.convert_vhd(self._FAKE_VHD_PATH,
                                  self._FAKE_DESTINATION_PATH,
                                  self._FAKE_TYPE)

        self.mock_img_svc.ConvertVirtualHardDisk.assert_called_once()
        self.wutils.check_ret_val.assert_called_once_with(
            self._FAKE_RET_VAL, self._FAKE_JOB_PATH)

    def test_resize_vhd(self):
        self.mock_img_svc.ExpandVirtualHardDisk.return_value = (
            self._FAKE_JOB_PATH, self._FAKE_RET_VAL)

        self.vhdutils.resize_vhd(self._FAKE_VHD_PATH,
                                 self._FAKE_VHD_SIZE)

        self.mock_img_svc.ExpandVirtualHardDisk.assert_called_once()
        self.wutils.check_ret_val.assert_called_once_with(self._FAKE_RET_VAL,
                                                          self._FAKE_JOB_PATH)
        self.vhdutils._get_resize_method.assert_called_once()
        self.mock_img_svc.ExpandVirtualHardDisk.assert_called_once_with(
            Path=self._FAKE_VHD_PATH, MaxInternalSize=self._FAKE_VHD_SIZE)
