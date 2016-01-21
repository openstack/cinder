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

import os

from os_brick.remotefs import remotefs
from os_win import utilsfactory

from cinder import exception
from cinder.i18n import _


class WindowsRemoteFsClient(remotefs.RemoteFsClient):
    def __init__(self, *args, **kwargs):
        super(WindowsRemoteFsClient, self).__init__(*args, **kwargs)
        self._smbutils = utilsfactory.get_smbutils()
        self._pathutils = utilsfactory.get_pathutils()

    def mount(self, export_path, mnt_options=None):
        if not os.path.isdir(self._mount_base):
            os.makedirs(self._mount_base)

        mnt_point = self.get_mount_point(export_path)
        norm_path = os.path.abspath(export_path)
        mnt_options = mnt_options or {}

        username = (mnt_options.get('username') or
                    mnt_options.get('user'))
        password = (mnt_options.get('password') or
                    mnt_options.get('pass'))

        if not self._smbutils.check_smb_mapping(
                norm_path,
                remove_unavailable_mapping=True):
            self._smbutils.mount_smb_share(norm_path,
                                           username=username,
                                           password=password)

        if os.path.exists(mnt_point):
            if not self._pathutils.is_symlink(mnt_point):
                raise exception.SmbfsException(_("Link path already exists "
                                                 "and its not a symlink"))
        else:
            self._pathutils.create_sym_link(mnt_point, norm_path)
