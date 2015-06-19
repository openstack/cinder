# Copyright (c) 2015 Hitachi Data Systems, Inc.
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

"""Volume copy throttling helpers."""


import contextlib

from oslo_concurrency import processutils
from oslo_log import log as logging

from cinder import exception
from cinder.i18n import _LW, _LE
from cinder import utils


LOG = logging.getLogger(__name__)


class Throttle(object):
    """Base class for throttling disk I/O bandwidth"""

    DEFAULT = None

    @staticmethod
    def set_default(throttle):
        Throttle.DEFAULT = throttle

    @staticmethod
    def get_default():
        return Throttle.DEFAULT or Throttle()

    def __init__(self, prefix=None):
        self.prefix = prefix or []

    @contextlib.contextmanager
    def subcommand(self, srcpath, dstpath):
        """Throttle disk I/O bandwidth used by a sub-command, such as 'dd',
        that reads from srcpath and writes to dstpath. The sub-command
        must be executed with the generated prefix command.
        """
        yield {'prefix': self.prefix}


class BlkioCgroup(Throttle):
    """Throttle disk I/O bandwidth using blkio cgroups."""

    def __init__(self, bps_limit, cgroup_name):
        self.bps_limit = bps_limit
        self.cgroup = cgroup_name
        self.srcdevs = {}
        self.dstdevs = {}

        try:
            utils.execute('cgcreate', '-g', 'blkio:%s' % self.cgroup,
                          run_as_root=True)
        except processutils.ProcessExecutionError:
            LOG.error(_LE('Failed to create blkio cgroup \'%(name)s\'.'),
                      {'name': cgroup_name})
            raise

    def _get_device_number(self, path):
        try:
            return utils.get_blkdev_major_minor(path)
        except exception.Error as e:
            LOG.error(_LE('Failed to get device number for throttling: '
                          '%(error)s'), {'error': e})

    def _limit_bps(self, rw, dev, bps):
        try:
            utils.execute('cgset', '-r', 'blkio.throttle.%s_bps_device=%s %d'
                          % (rw, dev, bps), self.cgroup, run_as_root=True)
        except processutils.ProcessExecutionError:
            LOG.warning(_LW('Failed to setup blkio cgroup to throttle the '
                            'device \'%(device)s\'.'), {'device': dev})

    def _set_limits(self, rw, devs):
        total = sum(devs.values())
        for dev in devs:
            self._limit_bps(rw, dev, self.bps_limit * devs[dev] / total)

    @utils.synchronized('BlkioCgroup')
    def _inc_device(self, srcdev, dstdev):
        if srcdev:
            self.srcdevs[srcdev] = self.srcdevs.get(srcdev, 0) + 1
            self._set_limits('read', self.srcdevs)
        if dstdev:
            self.dstdevs[dstdev] = self.dstdevs.get(dstdev, 0) + 1
            self._set_limits('write', self.dstdevs)

    @utils.synchronized('BlkioCgroup')
    def _dec_device(self, srcdev, dstdev):
        if srcdev:
            self.srcdevs[srcdev] -= 1
            if self.srcdevs[srcdev] == 0:
                del self.srcdevs[srcdev]
            self._set_limits('read', self.srcdevs)
        if dstdev:
            self.dstdevs[dstdev] -= 1
            if self.dstdevs[dstdev] == 0:
                del self.dstdevs[dstdev]
            self._set_limits('write', self.dstdevs)

    @contextlib.contextmanager
    def subcommand(self, srcpath, dstpath):
        srcdev = self._get_device_number(srcpath)
        dstdev = self._get_device_number(dstpath)

        if srcdev is None and dstdev is None:
            yield {'prefix': []}
            return

        self._inc_device(srcdev, dstdev)
        try:
            yield {'prefix': ['cgexec', '-g', 'blkio:%s' % self.cgroup]}
        finally:
            self._dec_device(srcdev, dstdev)
