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
from cinder.volume.drivers.windows import remotefs


class WindowsRemoteFsTestCase(test.TestCase):
    def setUp(self):
        super(WindowsRemoteFsTestCase, self).setUp()

        with mock.patch.object(remotefs.WindowsRemoteFsClient,
                               '__init__', lambda x: None):
            self._remotefs = remotefs.WindowsRemoteFsClient()

        self._remotefs._mount_base = mock.sentinel.mnt_base
        self._remotefs._smbutils = mock.Mock()
        self._remotefs._pathutils = mock.Mock()

    @mock.patch('os.path.isdir')
    @mock.patch('os.makedirs')
    @mock.patch('os.path.exists')
    @mock.patch('os.path.abspath')
    @mock.patch.object(remotefs.WindowsRemoteFsClient, 'get_mount_point')
    def _test_mount_share(self, mock_get_mnt_point, mock_abspath,
                          mock_path_exists, mock_makedirs, mock_isdir,
                          mnt_point_exists=False, is_mnt_point_slink=True):
        mount_options = dict(username=mock.sentinel.username,
                             password=mock.sentinel.password)
        mock_isdir.return_value = False
        mock_get_mnt_point.return_value = mock.sentinel.mnt_point
        mock_abspath.return_value = mock.sentinel.norm_export_path
        mock_path_exists.return_value = mnt_point_exists

        self._remotefs._pathutils.is_symlink.return_value = is_mnt_point_slink
        self._remotefs._smbutils.check_smb_mapping.return_value = False

        if mnt_point_exists and not is_mnt_point_slink:
            self.assertRaises(exception.SmbfsException,
                              self._remotefs.mount,
                              mock.sentinel.export_path,
                              mount_options)
        else:
            self._remotefs.mount(mock.sentinel.export_path, mount_options)

        mock_makedirs.assert_called_once_with(mock.sentinel.mnt_base)
        mock_get_mnt_point.assert_called_once_with(mock.sentinel.export_path)
        self._remotefs._smbutils.check_smb_mapping.assert_called_once_with(
            mock.sentinel.norm_export_path, remove_unavailable_mapping=True)
        self._remotefs._smbutils.mount_smb_share.assert_called_once_with(
            mock.sentinel.norm_export_path, **mount_options)

        if not mnt_point_exists:
            self._remotefs._pathutils.create_sym_link.assert_called_once_with(
                mock.sentinel.mnt_point, mock.sentinel.norm_export_path)

    def test_mount_share(self):
        self._test_mount_share()

    def test_mount_share_existing_mnt_point_not_symlink(self):
        self._test_mount_share(mnt_point_exists=True,
                               is_mnt_point_slink=False)
