# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 OpenStack Foundation.
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

import executor
import host_driver
import linuxscsi
import os
import time

from oslo.config import cfg

from cinder import exception
from cinder.openstack.common.gettextutils import _
from cinder.openstack.common import lockutils
from cinder.openstack.common import log as logging
from cinder.openstack.common import processutils as putils

LOG = logging.getLogger(__name__)
CONF = cfg.CONF
synchronized = lockutils.synchronized_with_prefix('brick-')


class InitiatorConnector(executor.Executor):
    def __init__(self, driver=None, execute=putils.execute,
                 root_helper="sudo", *args, **kwargs):
        super(InitiatorConnector, self).__init__(execute, root_helper,
                                                 *args, **kwargs)
        if not driver:
            driver = host_driver.HostDriver()
        self.set_driver(driver)

        self._linuxscsi = linuxscsi.LinuxSCSI(execute, root_helper)

    def set_driver(self, driver):
        """The driver used to find used LUNs."""

        self.driver = driver

    def connect_volume(self, connection_properties):
        raise NotImplementedError()

    def disconnect_volume(self, connection_properties):
        raise NotImplementedError()


class ISCSIConnector(InitiatorConnector):
    """"Connector class to attach/detach iSCSI volumes."""

    def __init__(self, driver=None, execute=putils.execute,
                 root_helper="sudo", use_multipath=False,
                 *args, **kwargs):
        super(ISCSIConnector, self).__init__(driver, execute, root_helper,
                                             *args, **kwargs)
        self.use_multipath = use_multipath

    @synchronized('connect_volume')
    def connect_volume(self, connection_properties):
        """Attach the volume to instance_name.

        connection_properties for iSCSI must include:
        target_portal - ip and optional port
        target_iqn - iSCSI Qualified Name
        target_lun - LUN id of the volume
        """

        device_info = {'type': 'block'}

        if self.use_multipath:
            #multipath installed, discovering other targets if available
            target_portal = connection_properties['target_portal']
            out = self._run_iscsiadm_bare(['-m',
                                          'discovery',
                                          '-t',
                                          'sendtargets',
                                          '-p',
                                          target_portal],
                                          check_exit_code=[0, 255])[0] \
                or ""

            for ip in self._get_target_portals_from_iscsiadm_output(out):
                props = connection_properties.copy()
                props['target_portal'] = ip
                self._connect_to_iscsi_portal(props)

            self._rescan_iscsi()
        else:
            self._connect_to_iscsi_portal(connection_properties)

        host_device = self._get_device_path(connection_properties)

        # The /dev/disk/by-path/... node is not always present immediately
        # TODO(justinsb): This retry-with-delay is a pattern, move to utils?
        tries = 0
        while not os.path.exists(host_device):
            if tries >= CONF.num_iscsi_scan_tries:
                raise exception.CinderException(
                    _("iSCSI device not found at %s") % (host_device))

            LOG.warn(_("ISCSI volume not yet found at: %(host_device)s. "
                       "Will rescan & retry.  Try number: %(tries)s"),
                     {'host_device': host_device,
                      'tries': tries})

            # The rescan isn't documented as being necessary(?), but it helps
            self._run_iscsiadm(connection_properties, ("--rescan",))

            tries = tries + 1
            if not os.path.exists(host_device):
                time.sleep(tries ** 2)

        if tries != 0:
            LOG.debug(_("Found iSCSI node %(host_device)s "
                        "(after %(tries)s rescans)"),
                      {'host_device': host_device, 'tries': tries})

        if self.use_multipath:
            #we use the multipath device instead of the single path device
            self._rescan_multipath()
            multipath_device = self._get_multipath_device_name(host_device)
            if multipath_device is not None:
                host_device = multipath_device

        device_info['path'] = host_device
        return device_info

    @synchronized('connect_volume')
    def disconnect_volume(self, connection_properties):
        """Detach the volume from instance_name.

        connection_properties for iSCSI must include:
        target_portal - ip and optional port
        target_iqn - iSCSI Qualified Name
        target_lun - LUN id of the volume
        """
        host_device = self._get_device_path(connection_properties)
        multipath_device = None
        if self.use_multipath:
            multipath_device = self._get_multipath_device_name(host_device)
            if multipath_device:
                self._linuxscsi.remove_multipath_device(multipath_device)
                return self._disconnect_volume_multipath_iscsi(
                    connection_properties, multipath_device)

        # remove the device from the scsi subsystem
        # this eliminates any stale entries until logout
        dev_name = self._linuxscsi.get_name_from_path(host_device)
        if dev_name:
            self._linuxscsi.remove_scsi_device(dev_name)

        # NOTE(vish): Only disconnect from the target if no luns from the
        #             target are in use.
        device_prefix = ("/dev/disk/by-path/ip-%(portal)s-iscsi-%(iqn)s-lun-" %
                         {'portal': connection_properties['target_portal'],
                          'iqn': connection_properties['target_iqn']})
        devices = self.driver.get_all_block_devices()
        devices = [dev for dev in devices if dev.startswith(device_prefix)]

        if not devices:
            self._disconnect_from_iscsi_portal(connection_properties)

    def _get_device_path(self, connection_properties):
        path = ("/dev/disk/by-path/ip-%(portal)s-iscsi-%(iqn)s-lun-%(lun)s" %
                {'portal': connection_properties['target_portal'],
                 'iqn': connection_properties['target_iqn'],
                 'lun': connection_properties.get('target_lun', 0)})
        return path

    def _run_iscsiadm(self, connection_properties, iscsi_command, **kwargs):
        check_exit_code = kwargs.pop('check_exit_code', 0)
        (out, err) = self._execute('iscsiadm', '-m', 'node', '-T',
                                   connection_properties['target_iqn'],
                                   '-p',
                                   connection_properties['target_portal'],
                                   *iscsi_command, run_as_root=True,
                                   root_helper=self._root_helper,
                                   check_exit_code=check_exit_code)
        LOG.debug("iscsiadm %s: stdout=%s stderr=%s" %
                  (iscsi_command, out, err))
        return (out, err)

    def _iscsiadm_update(self, connection_properties, property_key,
                         property_value, **kwargs):
        iscsi_command = ('--op', 'update', '-n', property_key,
                         '-v', property_value)
        return self._run_iscsiadm(connection_properties, iscsi_command,
                                  **kwargs)

    def _get_target_portals_from_iscsiadm_output(self, output):
        return [line.split()[0] for line in output.splitlines()]

    def _disconnect_volume_multipath_iscsi(self, connection_properties,
                                           multipath_name):
        """This removes a multipath device and it's LUNs."""
        LOG.debug("Disconnect multipath device %s" % multipath_name)
        self._rescan_iscsi()
        self._rescan_multipath()
        block_devices = self.driver.get_all_block_devices()
        devices = []
        for dev in block_devices:
            if "/mapper/" in dev:
                devices.append(dev)
            else:
                mpdev = self._get_multipath_device_name(dev)
                if mpdev:
                    devices.append(mpdev)

        if not devices:
            # disconnect if no other multipath devices
            self._disconnect_mpath(connection_properties)
            return

        other_iqns = [self._get_multipath_iqn(device)
                      for device in devices]

        if connection_properties['target_iqn'] not in other_iqns:
            # disconnect if no other multipath devices with same iqn
            self._disconnect_mpath(connection_properties)
            return

        # else do not disconnect iscsi portals,
        # as they are used for other luns
        return

    def _connect_to_iscsi_portal(self, connection_properties):
        # NOTE(vish): If we are on the same host as nova volume, the
        #             discovery makes the target so we don't need to
        #             run --op new. Therefore, we check to see if the
        #             target exists, and if we get 255 (Not Found), then
        #             we run --op new. This will also happen if another
        #             volume is using the same target.
        try:
            self._run_iscsiadm(connection_properties, ())
        except putils.ProcessExecutionError as exc:
            # iscsiadm returns 21 for "No records found" after version 2.0-871
            if exc.exit_code in [21, 255]:
                self._run_iscsiadm(connection_properties, ('--op', 'new'))
            else:
                raise

        if connection_properties.get('auth_method'):
            self._iscsiadm_update(connection_properties,
                                  "node.session.auth.authmethod",
                                  connection_properties['auth_method'])
            self._iscsiadm_update(connection_properties,
                                  "node.session.auth.username",
                                  connection_properties['auth_username'])
            self._iscsiadm_update(connection_properties,
                                  "node.session.auth.password",
                                  connection_properties['auth_password'])

        #duplicate logins crash iscsiadm after load,
        #so we scan active sessions to see if the node is logged in.
        out = self._run_iscsiadm_bare(["-m", "session"],
                                      run_as_root=True,
                                      check_exit_code=[0, 1, 21])[0] or ""

        portals = [{'portal': p.split(" ")[2], 'iqn': p.split(" ")[3]}
                   for p in out.splitlines() if p.startswith("tcp:")]

        stripped_portal = connection_properties['target_portal'].split(",")[0]
        if len(portals) == 0 or len([s for s in portals
                                     if stripped_portal ==
                                     s['portal'].split(",")[0]
                                     and
                                     s['iqn'] ==
                                     connection_properties['target_iqn']]
                                    ) == 0:
            try:
                self._run_iscsiadm(connection_properties,
                                   ("--login",),
                                   check_exit_code=[0, 255])
            except putils.ProcessExecutionError as err:
                #as this might be one of many paths,
                #only set successfull logins to startup automatically
                if err.exit_code in [15]:
                    self._iscsiadm_update(connection_properties,
                                          "node.startup",
                                          "automatic")
                    return

            self._iscsiadm_update(connection_properties,
                                  "node.startup",
                                  "automatic")

    def _disconnect_from_iscsi_portal(self, connection_properties):
        self._iscsiadm_update(connection_properties, "node.startup", "manual",
                              check_exit_code=[0, 21, 255])
        self._run_iscsiadm(connection_properties, ("--logout",),
                           check_exit_code=[0, 21, 255])
        self._run_iscsiadm(connection_properties, ('--op', 'delete'),
                           check_exit_code=[0, 21, 255])

    def _get_multipath_device_name(self, single_path_device):
        device = os.path.realpath(single_path_device)
        out = self._run_multipath(['-ll',
                                  device],
                                  check_exit_code=[0, 1])[0]
        mpath_line = [line for line in out.splitlines()
                      if "scsi_id" not in line]  # ignore udev errors
        if len(mpath_line) > 0 and len(mpath_line[0]) > 0:
            return "/dev/mapper/%s" % mpath_line[0].split(" ")[0]

        return None

    def _get_iscsi_devices(self):
        try:
            devices = list(os.walk('/dev/disk/by-path'))[0][-1]
        except IndexError:
            return []
        return [entry for entry in devices if entry.startswith("ip-")]

    def _disconnect_mpath(self, connection_properties):
        entries = self._get_iscsi_devices()
        ips = [ip.split("-")[1] for ip in entries
               if connection_properties['target_iqn'] in ip]
        for ip in ips:
            props = connection_properties.copy()
            props['target_portal'] = ip
            self._disconnect_from_iscsi_portal(props)

        self._rescan_multipath()

    def _get_multipath_iqn(self, multipath_device):
        entries = self._get_iscsi_devices()
        for entry in entries:
            entry_real_path = os.path.realpath("/dev/disk/by-path/%s" % entry)
            entry_multipath = self._get_multipath_device_name(entry_real_path)
            if entry_multipath == multipath_device:
                return entry.split("iscsi-")[1].split("-lun")[0]
        return None

    def _run_iscsiadm_bare(self, iscsi_command, **kwargs):
        check_exit_code = kwargs.pop('check_exit_code', 0)
        (out, err) = self._execute('iscsiadm',
                                   *iscsi_command,
                                   run_as_root=True,
                                   root_helper=self._root_helper,
                                   check_exit_code=check_exit_code)
        LOG.debug("iscsiadm %s: stdout=%s stderr=%s" %
                  (iscsi_command, out, err))
        return (out, err)

    def _run_multipath(self, multipath_command, **kwargs):
        check_exit_code = kwargs.pop('check_exit_code', 0)
        (out, err) = self._execute('multipath',
                                   *multipath_command,
                                   run_as_root=True,
                                   root_helper=self._root_helper,
                                   check_exit_code=check_exit_code)
        LOG.debug("multipath %s: stdout=%s stderr=%s" %
                  (multipath_command, out, err))
        return (out, err)

    def _rescan_iscsi(self):
        self._run_iscsiadm_bare(('-m', 'node', '--rescan'),
                                check_exit_code=[0, 1, 21, 255])
        self._run_iscsiadm_bare(('-m', 'session', '--rescan'),
                                check_exit_code=[0, 1, 21, 255])

    def _rescan_multipath(self):
        self._run_multipath('-r', check_exit_code=[0, 1, 21])
