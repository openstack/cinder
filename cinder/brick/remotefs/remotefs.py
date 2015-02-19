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
import re

from oslo_concurrency import processutils as putils
from oslo_log import log as logging
import six

from cinder.brick import exception
from cinder.i18n import _, _LI

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
            self._check_nfs_options()
        elif mount_type == "cifs":
            self._mount_base = kwargs.get('smbfs_mount_point_base', None)
            if not self._mount_base:
                raise exception.InvalidParameterValue(
                    err=_('smbfs_mount_point_base required'))
            self._mount_options = kwargs.get('smbfs_mount_options', None)
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
        (out, _err) = self._execute('mount', check_exit_code=0)
        lines = out.split('\n')
        mounts = {}
        for line in lines:
            tokens = line.split()
            if 2 < len(tokens):
                device = tokens[0]
                mnt_point = tokens[2]
                mounts[mnt_point] = device
        return mounts

    def mount(self, share, flags=None):
        """Mount given share."""
        mount_path = self.get_mount_point(share)

        if mount_path in self._read_mounts():
            LOG.info(_LI('Already mounted: %s') % mount_path)
            return

        self._execute('mkdir', '-p', mount_path, check_exit_code=0)
        if self._mount_type == 'nfs':
            self._mount_nfs(share, mount_path, flags)
        else:
            self._do_mount(self._mount_type, share, mount_path,
                           self._mount_options, flags)

    def _do_mount(self, mount_type, share, mount_path, mount_options=None,
                  flags=None):
        """Mounts share based on the specified params."""
        mnt_cmd = ['mount', '-t', mount_type]
        if mount_options is not None:
            mnt_cmd.extend(['-o', mount_options])
        if flags is not None:
            mnt_cmd.extend(flags)
        mnt_cmd.extend([share, mount_path])

        self._execute(*mnt_cmd, root_helper=self.root_helper,
                      run_as_root=True, check_exit_code=0)

    def _mount_nfs(self, nfs_share, mount_path, flags=None):
        """Mount nfs share using present mount types."""
        mnt_errors = {}

        # This loop allows us to first try to mount with NFS 4.1 for pNFS
        # support but falls back to mount NFS 4 or NFS 3 if either the client
        # or server do not support it.
        for mnt_type in sorted(self._nfs_mount_type_opts.keys(), reverse=True):
            options = self._nfs_mount_type_opts[mnt_type]
            try:
                self._do_mount('nfs', nfs_share, mount_path, options, flags)
                LOG.debug('Mounted %(sh)s using %(mnt_type)s.'
                          % {'sh': nfs_share, 'mnt_type': mnt_type})
                return
            except Exception as e:
                mnt_errors[mnt_type] = six.text_type(e)
                LOG.debug('Failed to do %s mount.', mnt_type)
        raise exception.BrickException(_("NFS mount failed for share %(sh)s. "
                                         "Error - %(error)s")
                                       % {'sh': nfs_share,
                                          'error': mnt_errors})

    def _check_nfs_options(self):
        """Checks and prepares nfs mount type options."""
        self._nfs_mount_type_opts = {'nfs': self._mount_options}
        nfs_vers_opt_patterns = ['^nfsvers', '^vers', '^v[\d]']
        for opt in nfs_vers_opt_patterns:
            if self._option_exists(self._mount_options, opt):
                return

        # pNFS requires NFS 4.1. The mount.nfs4 utility does not automatically
        # negotiate 4.1 support, we have to ask for it by specifying two
        # options: vers=4 and minorversion=1.
        pnfs_opts = self._update_option(self._mount_options, 'vers', '4')
        pnfs_opts = self._update_option(pnfs_opts, 'minorversion', '1')
        self._nfs_mount_type_opts['pnfs'] = pnfs_opts

    def _option_exists(self, options, opt_pattern):
        """Checks if the option exists in nfs options and returns position."""
        options = [x.strip() for x in options.split(',')] if options else []
        pos = 0
        for opt in options:
            pos = pos + 1
            if re.match(opt_pattern, opt, flags=0):
                return pos
        return 0

    def _update_option(self, options, option, value=None):
        """Update option if exists else adds it and returns new options."""
        opts = [x.strip() for x in options.split(',')] if options else []
        pos = self._option_exists(options, option)
        if pos:
            opts.pop(pos - 1)
        opt = '%s=%s' % (option, value) if value else option
        opts.append(opt)
        return ",".join(opts) if len(opts) > 1 else opts[0]
