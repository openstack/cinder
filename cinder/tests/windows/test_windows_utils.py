#  Copyright 2015 Cloudbase Solutions Srl
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
from cinder.volume.drivers.windows import windows_utils


class WindowsUtilsTestCase(test.TestCase):

    def setUp(self):
        super(WindowsUtilsTestCase, self).setUp()

        windows_utils.WindowsUtils.__init__ = lambda x: None
        self.wutils = windows_utils.WindowsUtils()
        self.wutils._conn_cimv2 = mock.MagicMock()

    def _test_copy_vhd_disk(self, source_exists=True, copy_failed=False):
        fake_data_file_object = mock.MagicMock()
        fake_data_file_object.Copy.return_value = [int(copy_failed)]

        fake_vhd_list = [fake_data_file_object] if source_exists else []
        mock_query = mock.Mock(return_value=fake_vhd_list)
        self.wutils._conn_cimv2.query = mock_query

        if not source_exists or copy_failed:
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.wutils.copy_vhd_disk,
                              mock.sentinel.src,
                              mock.sentinel.dest)
        else:
            self.wutils.copy_vhd_disk(mock.sentinel.src, mock.sentinel.dest)

            expected_query = (
                "Select * from CIM_DataFile where Name = '%s'" %
                mock.sentinel.src)
            mock_query.assert_called_once_with(expected_query)
            fake_data_file_object.Copy.assert_called_with(
                mock.sentinel.dest)

    def test_copy_vhd_disk(self):
        self._test_copy_vhd_disk()

    def test_copy_vhd_disk_invalid_source(self):
        self._test_copy_vhd_disk(source_exists=False)

    def test_copy_vhd_disk_copy_failed(self):
        self._test_copy_vhd_disk(copy_failed=True)
