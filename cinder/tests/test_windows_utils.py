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
from cinder.volume.drivers.windows import windows_utils


class WindowsUtilsTestCase(test.TestCase):

    _FAKE_FORMAT = 2
    _FAKE_TYPE = 3
    _FAKE_JOB_PATH = 'fake_job_path'
    _FAKE_VHD_PATH = r'C:\fake\vhd.vhd'
    _FAKE_DESTINATION_PATH = r'C:\fake\destination.vhd'
    _FAKE_RET_VAL = 0
    _FAKE_RET_VAL_ERROR = 10
    _FAKE_VHD_SIZE = 1024
    _FAKE_JOB = 'fake_job'

    def setUp(self):
        super(WindowsUtilsTestCase, self).setUp()
        windows_utils.WindowsUtils.__init__ = lambda x: None
        self.wutils = windows_utils.WindowsUtils()
        self.wutils._conn_virt = mock.MagicMock()
        self.wutils.time = mock.MagicMock()

    def test_convert_vhd(self):
        self.wutils.check_ret_val = mock.MagicMock()
        mock_img_svc = self.wutils._conn_virt.Msvm_ImageManagementService()[0]
        mock_img_svc.ConvertVirtualHardDisk.return_value = (
            self._FAKE_JOB_PATH, self._FAKE_RET_VAL)

        self.wutils.convert_vhd(self._FAKE_VHD_PATH,
                                self._FAKE_DESTINATION_PATH,
                                self._FAKE_TYPE)

        mock_img_svc.ConvertVirtualHardDisk.assert_called_once()
        self.wutils.check_ret_val.assert_called_once_with(
            self._FAKE_RET_VAL, self._FAKE_JOB_PATH)

    def test_resize_vhd(self):
        self.wutils.check_ret_val = mock.MagicMock()
        mock_img_svc = self.wutils._conn_virt.Msvm_ImageManagementService()[0]
        mock_img_svc.ExpandVirtualHardDisk.return_value = (self._FAKE_JOB_PATH,
                                                           self._FAKE_RET_VAL)

        self.wutils.resize_vhd(self._FAKE_VHD_PATH,
                               self._FAKE_VHD_SIZE)

        mock_img_svc.ExpandVirtualHardDisk.assert_called_once()
        self.wutils.check_ret_val.assert_called_once_with(self._FAKE_RET_VAL,
                                                          self._FAKE_JOB_PATH)

    def _test_check_ret_val(self, job_started, job_failed):
        self.wutils._wait_for_job = mock.Mock(return_value=self._FAKE_JOB)
        if job_started:
            ret_val = self.wutils.check_ret_val(
                constants.WMI_JOB_STATUS_STARTED, self._FAKE_JOB_PATH)
            self.assertEqual(ret_val, self._FAKE_JOB)
            self.wutils._wait_for_job.assert_called_once_with(
                self._FAKE_JOB_PATH)

        elif job_failed:
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.wutils.check_ret_val,
                              10, self._FAKE_JOB_PATH)

    def test_check_ret_val_failed_job(self):
        self._test_check_ret_val(False, True)

    def test_check_ret_val_job_started(self):
        self._test_check_ret_val(True, False)

    def _test_wait_for_job(self, job_running, job_failed):
        fake_job = mock.MagicMock()
        fake_job2 = mock.MagicMock()
        fake_job2.JobState = constants.WMI_JOB_STATE_COMPLETED

        if job_running:
            fake_job.JobState = constants.WMI_JOB_STATE_RUNNING
        elif job_failed:
            fake_job.JobState = self._FAKE_RET_VAL_ERROR
            fake_job.GetError = mock.Mock(return_value=(
                1, self._FAKE_RET_VAL_ERROR))
        else:
            fake_job.JobState = constants.WMI_JOB_STATE_COMPLETED

        self.wutils._get_wmi_obj = mock.Mock(side_effect=[fake_job, fake_job2])

        if job_failed:
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.wutils._wait_for_job,
                              self._FAKE_JOB_PATH)
        else:
            self.wutils._wait_for_job(self._FAKE_JOB_PATH)
            if job_running:
                call_count = 2
            else:
                call_count = 1
            self.assertEqual(call_count, self.wutils._get_wmi_obj.call_count)

    def test_wait_for_running_job(self):
        self._test_wait_for_job(True, False)

    def test_wait_for_failed_job(self):
        self._test_wait_for_job(False, True)
