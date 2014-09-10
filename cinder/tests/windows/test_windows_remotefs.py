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

import ctypes
import os

import mock

from cinder import exception
from cinder import test
from cinder.volume.drivers.windows import remotefs


class WindowsRemoteFsTestCase(test.TestCase):
    _FAKE_SHARE = '//1.2.3.4/share1'
    _FAKE_MNT_BASE = 'C:\OpenStack\mnt'
    _FAKE_HASH = 'db0bf952c1734092b83e8990bd321131'
    _FAKE_MNT_POINT = os.path.join(_FAKE_MNT_BASE, _FAKE_HASH)
    _FAKE_SHARE_OPTS = '-o username=Administrator,password=12345'
    _FAKE_OPTIONS_DICT = {'username': 'Administrator',
                          'password': '12345'}

    def setUp(self):
        super(WindowsRemoteFsTestCase, self).setUp()

        remotefs.ctypes.windll = mock.MagicMock()
        remotefs.WindowsRemoteFsClient.__init__ = mock.Mock(return_value=None)

        self._remotefs = remotefs.WindowsRemoteFsClient(
            'cifs', root_helper=None,
            smbfs_mount_point_base=self._FAKE_MNT_BASE)
        self._remotefs._mount_base = self._FAKE_MNT_BASE
        self._remotefs.smb_conn = mock.MagicMock()
        self._remotefs.conn_cimv2 = mock.MagicMock()

    def _test_mount_share(self, mount_point_exists=True, is_symlink=True,
                          mount_base_exists=True):
        fake_exists = mock.Mock(return_value=mount_point_exists)
        fake_isdir = mock.Mock(return_value=mount_base_exists)
        fake_makedirs = mock.Mock()
        with mock.patch.multiple('os.path', exists=fake_exists,
                                 isdir=fake_isdir):
            with mock.patch('os.makedirs', fake_makedirs):
                self._remotefs.is_symlink = mock.Mock(
                    return_value=is_symlink)
                self._remotefs.create_sym_link = mock.MagicMock()
                self._remotefs._mount = mock.MagicMock()
                fake_norm_path = os.path.abspath(self._FAKE_SHARE)

                if mount_point_exists:
                    if not is_symlink:
                        self.assertRaises(exception.SmbfsException,
                                          self._remotefs.mount,
                                          self._FAKE_MNT_POINT,
                                          self._FAKE_OPTIONS_DICT)
                else:
                    self._remotefs.mount(self._FAKE_SHARE,
                                         self._FAKE_OPTIONS_DICT)
                    if not mount_base_exists:
                        fake_makedirs.assert_called_once_with(
                            self._FAKE_MNT_BASE)
                    self._remotefs._mount.assert_called_once_with(
                        fake_norm_path, self._FAKE_OPTIONS_DICT)
                    self._remotefs.create_sym_link.assert_called_once_with(
                        self._FAKE_MNT_POINT, fake_norm_path)

    def test_mount_linked_share(self):
        # The mountpoint contains a symlink targeting the share path
        self._test_mount_share(True)

    def test_mount_unlinked_share(self):
        self._test_mount_share(False)

    def test_mount_point_exception(self):
        # The mountpoint already exists but it is not a symlink
        self._test_mount_share(True, False)

    def test_mount_base_missing(self):
        # The mount point base dir does not exist
        self._test_mount_share(mount_base_exists=False)

    def _test_check_symlink(self, is_symlink=True, python_version=(2, 7),
                            is_dir=True):
        fake_isdir = mock.Mock(return_value=is_dir)
        fake_islink = mock.Mock(return_value=is_symlink)
        with mock.patch('sys.version_info', python_version):
            with mock.patch.multiple('os.path', isdir=fake_isdir,
                                     islink=fake_islink):
                if is_symlink:
                    ret_value = 0x400
                else:
                    ret_value = 0x80
                fake_get_attributes = mock.Mock(return_value=ret_value)
                ctypes.windll.kernel32.GetFileAttributesW = fake_get_attributes

                ret_value = self._remotefs.is_symlink(self._FAKE_MNT_POINT)
                if python_version >= (3, 2):
                    fake_islink.assert_called_once_with(self._FAKE_MNT_POINT)
                else:
                    fake_get_attributes.assert_called_once_with(
                        self._FAKE_MNT_POINT)
                    self.assertEqual(ret_value, is_symlink)

    def test_is_symlink(self):
        self._test_check_symlink()

    def test_is_not_symlink(self):
        self._test_check_symlink(False)

    def test_check_symlink_python_gt_3_2(self):
        self._test_check_symlink(python_version=(3, 3))

    def test_create_sym_link_exception(self):
        ctypes.windll.kernel32.CreateSymbolicLinkW.return_value = 0
        self.assertRaises(exception.VolumeBackendAPIException,
                          self._remotefs.create_sym_link,
                          self._FAKE_MNT_POINT, self._FAKE_SHARE)

    def _test_check_smb_mapping(self, existing_mappings=False,
                                share_available=False):
        with mock.patch('os.path.exists', lambda x: share_available):
            fake_mapping = mock.MagicMock()
            if existing_mappings:
                fake_mappings = [fake_mapping]
            else:
                fake_mappings = []

            self._remotefs.smb_conn.query.return_value = fake_mappings
            ret_val = self._remotefs.check_smb_mapping(self._FAKE_SHARE)

            if existing_mappings:
                if share_available:
                    self.assertTrue(ret_val)
                else:
                    fake_mapping.Remove.assert_called_once_with(True, True)
            else:
                self.assertFalse(ret_val)

    def test_check_mapping(self):
        self._test_check_smb_mapping()

    def test_remake_unavailable_mapping(self):
        self._test_check_smb_mapping(True, False)

    def test_available_mapping(self):
        self._test_check_smb_mapping(True, True)

    def test_mount_smb(self):
        fake_create = self._remotefs.smb_conn.Msft_SmbMapping.Create
        self._remotefs._mount(self._FAKE_SHARE, {})
        fake_create.assert_called_once_with(UserName=None,
                                            Password=None,
                                            RemotePath=self._FAKE_SHARE)
