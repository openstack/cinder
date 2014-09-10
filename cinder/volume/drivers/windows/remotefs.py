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
import sys

if sys.platform == 'win32':
    import wmi

from cinder.brick.remotefs import remotefs
from cinder import exception
from cinder.openstack.common.gettextutils import _
from cinder.openstack.common import log as logging

LOG = logging.getLogger(__name__)


class WindowsRemoteFsClient(remotefs.RemoteFsClient):
    _FILE_ATTRIBUTE_REPARSE_POINT = 0x0400

    def __init__(self, *args, **kwargs):
        super(WindowsRemoteFsClient, self).__init__(*args, **kwargs)
        self.smb_conn = wmi.WMI(moniker='root/Microsoft/Windows/SMB')
        self.conn_cimv2 = wmi.WMI(moniker='root/cimv2')

    def mount(self, export_path, mnt_options=None):
        if not os.path.isdir(self._mount_base):
            os.makedirs(self._mount_base)
        export_hash = self._get_hash_str(export_path)

        norm_path = os.path.abspath(export_path)
        mnt_options = mnt_options or {}

        if not self.check_smb_mapping(norm_path):
            self._mount(norm_path, mnt_options)

        link_path = os.path.join(self._mount_base, export_hash)
        if os.path.exists(link_path):
            if not self.is_symlink(link_path):
                raise exception.SmbfsException(_("Link path already exists "
                                                 "and its not a symlink"))
        else:
            self.create_sym_link(link_path, norm_path)

    def is_symlink(self, path):
        if sys.version_info >= (3, 2):
            return os.path.islink(path)

        file_attr = ctypes.windll.kernel32.GetFileAttributesW(unicode(path))

        return bool(os.path.isdir(path) and (
            file_attr & self._FILE_ATTRIBUTE_REPARSE_POINT))

    def create_sym_link(self, link, target, target_is_dir=True):
        """If target_is_dir is True, a junction will be created.

        NOTE: Juctions only work on same filesystem.
        """
        symlink = ctypes.windll.kernel32.CreateSymbolicLinkW
        symlink.argtypes = (
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_ulong,
        )
        symlink.restype = ctypes.c_ubyte
        retcode = symlink(link, target, target_is_dir)
        if retcode == 0:
            err_msg = (_("Could not create symbolic link. "
                         "Link: %(link)s Target %(target)s")
                       % {'link': link, 'target': target})
            raise exception.VolumeBackendAPIException(err_msg)

    def check_smb_mapping(self, smbfs_share):
        mappings = self.smb_conn.query("SELECT * FROM "
                                       "MSFT_SmbMapping "
                                       "WHERE RemotePath='%s'" %
                                       smbfs_share)

        if len(mappings) > 0:
            if os.path.exists(smbfs_share):
                LOG.debug('Share already mounted: %s' % smbfs_share)
                return True
            else:
                LOG.debug('Share exists but is unavailable: %s '
                          % smbfs_share)
                for mapping in mappings:
                    # Due to a bug in the WMI module, getting the output of
                    # methods returning None will raise an AttributeError
                    try:
                        mapping.Remove(True, True)
                    except AttributeError:
                        pass
        return False

    def _mount(self, smbfs_share, options):
        smb_opts = {'RemotePath': smbfs_share}
        smb_opts['UserName'] = (options.get('username') or
                                options.get('user'))
        smb_opts['Password'] = (options.get('password') or
                                options.get('pass'))

        try:
            LOG.info(_('Mounting share: %s') % smbfs_share)
            self.smb_conn.Msft_SmbMapping.Create(**smb_opts)
        except wmi.x_wmi as exc:
            err_msg = (_(
                'Unable to mount SMBFS share: %(smbfs_share)s '
                'WMI exception: %(wmi_exc)s'
                'Options: %(options)s') % {'smbfs_share': smbfs_share,
                                           'options': smb_opts,
                                           'wmi_exc': exc})
            raise exception.VolumeBackendAPIException(data=err_msg)

    def get_capacity_info(self, smbfs_share):
        norm_path = os.path.abspath(smbfs_share)
        kernel32 = ctypes.windll.kernel32

        free_bytes = ctypes.c_ulonglong(0)
        total_bytes = ctypes.c_ulonglong(0)
        retcode = kernel32.GetDiskFreeSpaceExW(ctypes.c_wchar_p(norm_path),
                                               None,
                                               ctypes.pointer(total_bytes),
                                               ctypes.pointer(free_bytes))
        if retcode == 0:
            LOG.error(_("Could not get share %s capacity info.") %
                      smbfs_share)
            return 0, 0
        return total_bytes.value, free_bytes.value
