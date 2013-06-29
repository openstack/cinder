# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 OpenStack Foundation
# All Rights Reserved
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

"""Remote filesystem client utilities."""

import hashlib
import os

from cinder.brick import exception
from cinder.openstack.common.gettextutils import _
from cinder.openstack.common import log as logging
from cinder.openstack.common import processutils as putils

LOG = logging.getLogger(__name__)


class RemoteFsClient(object):

    def __init__(self, mount_type, root_helper,
                 execute=putils.execute, *args, **kwargs):

        self._mount_type = mount_type
        if mount_type == "nfs":
            self._mount_base = kwargs.get('nfs_mount_point_base', None)
            if not self._mount_base:
                raise exception.InvalidParameterValue(
                    err=_('nfs_mount_point_base required'))
            self._mount_options = kwargs.get('nfs_mount_options', None)
        elif mount_type == "glusterfs":
            self._mount_base = kwargs.get('glusterfs_mount_point_base', None)
            if not self._mount_base:
                raise exception.InvalidParameterValue(
                    err=_('glusterfs_mount_point_base required'))
            self._mount_options = None
        else:
            raise exception.ProtocolNotSupported(protocol=mount_type)
        self.root_helper = root_helper
        self.set_execute(execute)

    def set_execute(self, execute):
        self._execute = execute

    def _get_hash_str(self, base_str):
        """Return a string that represents hash of base_str
        (in a hex format).
        """
        return hashlib.md5(base_str).hexdigest()

    def get_mount_point(self, device_name):
        """Get Mount Point.

        :param device_name: example 172.18.194.100:/var/nfs
        """
        return os.path.join(self._mount_base,
                            self._get_hash_str(device_name))

    def _read_mounts(self):
        (out, err) = self._execute('mount', check_exit_code=0)
        lines = out.split('\n')
        mounts = {}
        for line in lines:
            tokens = line.split()
            if 2 < len(tokens):
                device = tokens[0]
                mnt_point = tokens[2]
                mounts[mnt_point] = device
        return mounts

    def mount(self, nfs_share, flags=None):
        """Mount NFS share."""
        mount_path = self.get_mount_point(nfs_share)

        if mount_path in self._read_mounts():
            LOG.info(_('Already mounted: %s') % mount_path)
            return

        self._execute('mkdir', '-p', mount_path, check_exit_code=0)

        mnt_cmd = ['mount', '-t', self._mount_type]
        if self._mount_options is not None:
            mnt_cmd.extend(['-o', self._mount_options])
        if flags is not None:
            mnt_cmd.extend(flags)
        mnt_cmd.extend([nfs_share, mount_path])

        self._execute(*mnt_cmd, root_helper=self.root_helper,
                      run_as_root=True, check_exit_code=0)
