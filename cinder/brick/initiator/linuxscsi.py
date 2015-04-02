# (c) Copyright 2013 Hewlett-Packard Development Company, L.P.
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

"""Generic linux scsi subsystem and Multipath utilities.

   Note, this is not iSCSI.
"""
import os
import re

from oslo_concurrency import processutils as putils
from oslo_log import log as logging

from cinder.brick import exception
from cinder.brick import executor
from cinder.i18n import _, _LW, _LE
from cinder.openstack.common import loopingcall

LOG = logging.getLogger(__name__)

MULTIPATH_ERROR_REGEX = re.compile("\w{3} \d+ \d\d:\d\d:\d\d \|.*$")
MULTIPATH_WWID_REGEX = re.compile("\((?P<wwid>.+)\)")


class LinuxSCSI(executor.Executor):
    def __init__(self, root_helper, execute=putils.execute,
                 *args, **kwargs):
        super(LinuxSCSI, self).__init__(root_helper, execute,
                                        *args, **kwargs)

    def echo_scsi_command(self, path, content):
        """Used to echo strings to scsi subsystem."""

        args = ["-a", path]
        kwargs = dict(process_input=content,
                      run_as_root=True,
                      root_helper=self._root_helper)
        self._execute('tee', *args, **kwargs)

    def get_name_from_path(self, path):
        """Translates /dev/disk/by-path/ entry to /dev/sdX."""

        name = os.path.realpath(path)
        if name.startswith("/dev/"):
            return name
        else:
            return None

    def remove_scsi_device(self, device):
        """Removes a scsi device based upon /dev/sdX name."""

        path = "/sys/block/%s/device/delete" % device.replace("/dev/", "")
        if os.path.exists(path):
            # flush any outstanding IO first
            self.flush_device_io(device)

            LOG.debug("Remove SCSI device(%s) with %s" % (device, path))
            self.echo_scsi_command(path, "1")

    def wait_for_volume_removal(self, volume_path):
        """This is used to ensure that volumes are gone."""

        def _wait_for_volume_removal(volume_path):
            LOG.debug("Waiting for SCSI mount point %s to be removed.",
                      volume_path)
            if os.path.exists(volume_path):
                if self.tries >= self.scan_attempts:
                    msg = _LE("Exceeded the number of attempts to detect "
                              "volume removal.")
                    LOG.error(msg)
                    raise exception.VolumePathNotRemoved(
                        volume_path=volume_path)

                LOG.debug("%(path)s still exists, rescanning. Try number: "
                          "%(tries)s",
                          {'path': volume_path, 'tries': self.tries})
                self.tries = self.tries + 1
            else:
                LOG.debug("SCSI mount point %s has been removed.", volume_path)
                raise loopingcall.LoopingCallDone()

        # Setup a loop here to give the kernel time
        # to remove the volume from /dev/disk/by-path/
        self.tries = 0
        self.scan_attempts = 3
        timer = loopingcall.FixedIntervalLoopingCall(
            _wait_for_volume_removal, volume_path)
        timer.start(interval=2).wait()

    def get_device_info(self, device):
        (out, _err) = self._execute('sg_scan', device, run_as_root=True,
                                    root_helper=self._root_helper)
        dev_info = {'device': device, 'host': None,
                    'channel': None, 'id': None, 'lun': None}
        if out:
            line = out.strip()
            line = line.replace(device + ": ", "")
            info = line.split(" ")

            for item in info:
                if '=' in item:
                    pair = item.split('=')
                    dev_info[pair[0]] = pair[1]
                elif 'scsi' in item:
                    dev_info['host'] = item.replace('scsi', '')

        return dev_info

    def remove_multipath_device(self, multipath_name):
        """This removes LUNs associated with a multipath device
        and the multipath device itself.
        """

        LOG.debug("remove multipath device %s" % multipath_name)
        mpath_dev = self.find_multipath_device(multipath_name)
        if mpath_dev:
            devices = mpath_dev['devices']
            LOG.debug("multipath LUNs to remove %s" % devices)
            for device in devices:
                self.remove_scsi_device(device['device'])
            self.flush_multipath_device(mpath_dev['id'])

    def flush_device_io(self, device):
        """This is used to flush any remaining IO in the buffers."""
        try:
            LOG.debug("Flushing IO for device %s" % device)
            self._execute('blockdev', '--flushbufs', device, run_as_root=True,
                          root_helper=self._root_helper)
        except putils.ProcessExecutionError as exc:
            msg = _("Failed to flush IO buffers prior to removing"
                    " device: (%(code)s)") % {'code': exc.exit_code}
            LOG.warn(msg)

    def flush_multipath_device(self, device):
        try:
            LOG.debug("Flush multipath device %s" % device)
            self._execute('multipath', '-f', device, run_as_root=True,
                          root_helper=self._root_helper)
        except putils.ProcessExecutionError as exc:
            LOG.warn(_LW("multipath call failed exit (%(code)s)")
                     % {'code': exc.exit_code})

    def flush_multipath_devices(self):
        try:
            self._execute('multipath', '-F', run_as_root=True,
                          root_helper=self._root_helper)
        except putils.ProcessExecutionError as exc:
            LOG.warn(_LW("multipath call failed exit (%(code)s)")
                     % {'code': exc.exit_code})

    def find_multipath_device(self, device):
        """Find a multipath device associated with a LUN device name.

        device can be either a /dev/sdX entry or a multipath id.
        """

        mdev = None
        devices = []
        out = None
        try:
            (out, _err) = self._execute('multipath', '-l', device,
                                        run_as_root=True,
                                        root_helper=self._root_helper)
        except putils.ProcessExecutionError as exc:
            LOG.warn(_LW("multipath call failed exit (%(code)s)")
                     % {'code': exc.exit_code})
            return None

        if out:
            lines = out.strip()
            lines = lines.split("\n")
            lines = [line for line in lines
                     if not re.match(MULTIPATH_ERROR_REGEX, line)]
            if lines:

                # Use the device name, be it the WWID, mpathN or custom alias
                # of a device to build the device path. This should be the
                # first item on the first line of output from `multipath -l
                # ${path}` or `multipath -l ${wwid}`..
                mdev_name = lines[0].split(" ")[0]
                mdev = '/dev/mapper/%s' % mdev_name

                # Find the WWID for the LUN if we are using mpathN or aliases.
                wwid_search = MULTIPATH_WWID_REGEX.search(lines[0])
                if wwid_search is not None:
                    mdev_id = wwid_search.group('wwid')
                else:
                    mdev_id = mdev_name

                # Confirm that the device is present.
                try:
                    os.stat(mdev)
                except OSError:
                    LOG.warn(_LW("Couldn't find multipath device %s"), mdev)
                    return None

                LOG.debug("Found multipath device = %(mdev)s"
                          % {'mdev': mdev})
                device_lines = lines[3:]
                for dev_line in device_lines:
                    if dev_line.find("policy") != -1:
                        continue

                    dev_line = dev_line.lstrip(' |-`')
                    dev_info = dev_line.split()
                    address = dev_info[0].split(":")

                    dev = {'device': '/dev/%s' % dev_info[1],
                           'host': address[0], 'channel': address[1],
                           'id': address[2], 'lun': address[3]
                           }

                    devices.append(dev)

        if mdev is not None:
            info = {"device": mdev,
                    "id": mdev_id,
                    "name": mdev_name,
                    "devices": devices}
            return info
        return None
