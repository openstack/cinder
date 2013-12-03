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

import os
import socket
import time

from cinder.brick import exception
from cinder.brick import executor
from cinder.brick.initiator import host_driver
from cinder.brick.initiator import linuxfc
from cinder.brick.initiator import linuxscsi
from cinder.brick.remotefs import remotefs
from cinder.openstack.common.gettextutils import _
from cinder.openstack.common import lockutils
from cinder.openstack.common import log as logging
from cinder.openstack.common import loopingcall
from cinder.openstack.common import processutils as putils

LOG = logging.getLogger(__name__)

synchronized = lockutils.synchronized_with_prefix('brick-')
DEVICE_SCAN_ATTEMPTS_DEFAULT = 3


def get_connector_properties(root_helper, my_ip):
    """Get the connection properties for all protocols."""

    iscsi = ISCSIConnector(root_helper=root_helper)
    fc = linuxfc.LinuxFibreChannel(root_helper=root_helper)

    props = {}
    props['ip'] = my_ip
    props['host'] = socket.gethostname()
    initiator = iscsi.get_initiator()
    if initiator:
        props['initiator'] = initiator
    wwpns = fc.get_fc_wwpns()
    if wwpns:
        props['wwpns'] = wwpns
    wwnns = fc.get_fc_wwnns()
    if wwnns:
        props['wwnns'] = wwnns

    return props


class InitiatorConnector(executor.Executor):
    def __init__(self, root_helper, driver=None,
                 execute=putils.execute,
                 device_scan_attempts=DEVICE_SCAN_ATTEMPTS_DEFAULT,
                 *args, **kwargs):
        super(InitiatorConnector, self).__init__(root_helper, execute=execute,
                                                 *args, **kwargs)
        if not driver:
            driver = host_driver.HostDriver()
        self.set_driver(driver)
        self.device_scan_attempts = device_scan_attempts

    def set_driver(self, driver):
        """The driver is used to find used LUNs."""

        self.driver = driver

    @staticmethod
    def factory(protocol, root_helper, driver=None,
                execute=putils.execute, use_multipath=False,
                device_scan_attempts=DEVICE_SCAN_ATTEMPTS_DEFAULT,
                *args, **kwargs):
        """Build a Connector object based upon protocol."""
        LOG.debug("Factory for %s" % protocol)
        protocol = protocol.upper()
        if protocol == "ISCSI":
            return ISCSIConnector(root_helper=root_helper,
                                  driver=driver,
                                  execute=execute,
                                  use_multipath=use_multipath,
                                  device_scan_attempts=device_scan_attempts,
                                  *args, **kwargs)
        elif protocol == "ISER":
            return ISERConnector(root_helper=root_helper,
                                 driver=driver,
                                 execute=execute,
                                 use_multipath=use_multipath,
                                 device_scan_attempts=device_scan_attempts,
                                 *args, **kwargs)
        elif protocol == "FIBRE_CHANNEL":
            return FibreChannelConnector(root_helper=root_helper,
                                         driver=driver,
                                         execute=execute,
                                         use_multipath=use_multipath,
                                         device_scan_attempts=
                                         device_scan_attempts,
                                         *args, **kwargs)
        elif protocol == "AOE":
            return AoEConnector(root_helper=root_helper,
                                driver=driver,
                                execute=execute,
                                device_scan_attempts=device_scan_attempts,
                                *args, **kwargs)
        elif protocol == "NFS" or protocol == "GLUSTERFS":
            return RemoteFsConnector(mount_type=protocol.lower(),
                                     root_helper=root_helper,
                                     driver=driver,
                                     execute=execute,
                                     device_scan_attempts=device_scan_attempts,
                                     *args, **kwargs)
        elif protocol == "LOCAL":
            return LocalConnector(root_helper=root_helper,
                                  driver=driver,
                                  execute=execute,
                                  device_scan_attempts=device_scan_attempts,
                                  *args, **kwargs)
        else:
            msg = (_("Invalid InitiatorConnector protocol "
                     "specified %(protocol)s") %
                   dict(protocol=protocol))
            raise ValueError(msg)

    def check_valid_device(self, path):
        cmd = ('dd', 'if=%(path)s' % {"path": path},
               'of=/dev/null', 'count=1')
        out, info = None, None
        try:
            out, info = self._execute(*cmd, run_as_root=True,
                                      root_helper=self._root_helper)
        except putils.ProcessExecutionError as e:
            LOG.error(_("Failed to access the device on the path "
                        "%(path)s: %(error)s %(info)s.") %
                      {"path": path, "error": e.stderr,
                       "info": info})
            return False
        # If the info is none, the path does not exist.
        if info is None:
            return False
        return True

    def connect_volume(self, connection_properties):
        """Connect to a volume.

        The connection_properties describes the information needed by
        the specific protocol to use to make the connection.
        """
        raise NotImplementedError()

    def disconnect_volume(self, connection_properties, device_info):
        """Disconnect a volume from the local host.

        The connection_properties are the same as from connect_volume.
        The device_info is returned from connect_volume.
        """
        raise NotImplementedError()


class ISCSIConnector(InitiatorConnector):
    """Connector class to attach/detach iSCSI volumes."""

    def __init__(self, root_helper, driver=None,
                 execute=putils.execute, use_multipath=False,
                 device_scan_attempts=DEVICE_SCAN_ATTEMPTS_DEFAULT,
                 *args, **kwargs):
        self._linuxscsi = linuxscsi.LinuxSCSI(root_helper, execute)
        super(ISCSIConnector, self).__init__(root_helper, driver=driver,
                                             execute=execute,
                                             device_scan_attempts=
                                             device_scan_attempts,
                                             *args, **kwargs)
        self.use_multipath = use_multipath

    def set_execute(self, execute):
        super(ISCSIConnector, self).set_execute(execute)
        self._linuxscsi.set_execute(execute)

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
            if tries >= self.device_scan_attempts:
                raise exception.VolumeDeviceNotFound(device=host_device)

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
    def disconnect_volume(self, connection_properties, device_info):
        """Detach the volume from instance_name.

        connection_properties for iSCSI must include:
        target_portal - IP and optional port
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

    def get_initiator(self):
        """Secure helper to read file as root."""
        file_path = '/etc/iscsi/initiatorname.iscsi'
        try:
            lines, _err = self._execute('cat', file_path, run_as_root=True,
                                        root_helper=self._root_helper)

            for l in lines.split('\n'):
                if l.startswith('InitiatorName='):
                    return l[l.index('=') + 1:].strip()
        except putils.ProcessExecutionError:
            msg = (_("Could not find the iSCSI Initiator File %s")
                   % file_path)
            LOG.warn(msg)
            return None

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
                #only set successful logins to startup automatically
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


class ISERConnector(ISCSIConnector):

    def _get_device_path(self, iser_properties):
        return ("/dev/disk/by-path/ip-%s-iser-%s-lun-%s" %
                (iser_properties['target_portal'],
                 iser_properties['target_iqn'],
                 iser_properties.get('target_lun', 0)))


class FibreChannelConnector(InitiatorConnector):
    """Connector class to attach/detach Fibre Channel volumes."""

    def __init__(self, root_helper, driver=None,
                 execute=putils.execute, use_multipath=False,
                 device_scan_attempts=DEVICE_SCAN_ATTEMPTS_DEFAULT,
                 *args, **kwargs):
        self._linuxscsi = linuxscsi.LinuxSCSI(root_helper, execute)
        self._linuxfc = linuxfc.LinuxFibreChannel(root_helper, execute)
        super(FibreChannelConnector, self).__init__(root_helper, driver=driver,
                                                    execute=execute,
                                                    device_scan_attempts=
                                                    device_scan_attempts,
                                                    *args, **kwargs)
        self.use_multipath = use_multipath

    def set_execute(self, execute):
        super(FibreChannelConnector, self).set_execute(execute)
        self._linuxscsi.set_execute(execute)
        self._linuxfc.set_execute(execute)

    @synchronized('connect_volume')
    def connect_volume(self, connection_properties):
        """Attach the volume to instance_name.

        connection_properties for Fibre Channel must include:
        target_portal - ip and optional port
        target_iqn - iSCSI Qualified Name
        target_lun - LUN id of the volume
        """
        LOG.debug("execute = %s" % self._execute)
        device_info = {'type': 'block'}

        ports = connection_properties['target_wwn']
        wwns = []
        # we support a list of wwns or a single wwn
        if isinstance(ports, list):
            for wwn in ports:
                wwns.append(str(wwn))
        elif isinstance(ports, basestring):
            wwns.append(str(ports))

        # We need to look for wwns on every hba
        # because we don't know ahead of time
        # where they will show up.
        hbas = self._linuxfc.get_fc_hbas_info()
        host_devices = []
        for hba in hbas:
            pci_num = self._get_pci_num(hba)
            if pci_num is not None:
                for wwn in wwns:
                    target_wwn = "0x%s" % wwn.lower()
                    host_device = ("/dev/disk/by-path/pci-%s-fc-%s-lun-%s" %
                                  (pci_num,
                                   target_wwn,
                                   connection_properties.get('target_lun', 0)))
                    host_devices.append(host_device)

        if len(host_devices) == 0:
            # this is empty because we don't have any FC HBAs
            msg = _("We are unable to locate any Fibre Channel devices")
            LOG.warn(msg)
            raise exception.NoFibreChannelHostsFound()

        # The /dev/disk/by-path/... node is not always present immediately
        # We only need to find the first device.  Once we see the first device
        # multipath will have any others.
        def _wait_for_device_discovery(host_devices):
            tries = self.tries
            for device in host_devices:
                LOG.debug(_("Looking for Fibre Channel dev %(device)s"),
                          {'device': device})
                if os.path.exists(device):
                    self.host_device = device
                    # get the /dev/sdX device.  This is used
                    # to find the multipath device.
                    self.device_name = os.path.realpath(device)
                    raise loopingcall.LoopingCallDone()

            if self.tries >= self.device_scan_attempts:
                msg = _("Fibre Channel volume device not found.")
                LOG.error(msg)
                raise exception.NoFibreChannelVolumeDeviceFound()

            LOG.warn(_("Fibre volume not yet found. "
                       "Will rescan & retry.  Try number: %(tries)s"),
                     {'tries': tries})

            self._linuxfc.rescan_hosts(hbas)
            self.tries = self.tries + 1

        self.host_device = None
        self.device_name = None
        self.tries = 0
        timer = loopingcall.FixedIntervalLoopingCall(
            _wait_for_device_discovery, host_devices)
        timer.start(interval=2).wait()

        tries = self.tries
        if self.host_device is not None and self.device_name is not None:
            LOG.debug(_("Found Fibre Channel volume %(name)s "
                        "(after %(tries)s rescans)"),
                      {'name': self.device_name, 'tries': tries})

        # see if the new drive is part of a multipath
        # device.  If so, we'll use the multipath device.
        if self.use_multipath:
            mdev_info = self._linuxscsi.find_multipath_device(self.device_name)
            if mdev_info is not None:
                LOG.debug(_("Multipath device discovered %(device)s")
                          % {'device': mdev_info['device']})
                device_path = mdev_info['device']
                devices = mdev_info['devices']
                device_info['multipath_id'] = mdev_info['id']
            else:
                # we didn't find a multipath device.
                # so we assume the kernel only sees 1 device
                device_path = self.host_device
                dev_info = self._linuxscsi.get_device_info(self.device_name)
                devices = [dev_info]
        else:
            device_path = self.host_device
            dev_info = self._linuxscsi.get_device_info(self.device_name)
            devices = [dev_info]

        device_info['path'] = device_path
        device_info['devices'] = devices
        return device_info

    @synchronized('connect_volume')
    def disconnect_volume(self, connection_properties, device_info):
        """Detach the volume from instance_name.

        connection_properties for Fibre Channel must include:
        target_wwn - iSCSI Qualified Name
        target_lun - LUN id of the volume
        """
        devices = device_info['devices']

        # If this is a multipath device, we need to search again
        # and make sure we remove all the devices. Some of them
        # might not have shown up at attach time.
        if self.use_multipath and 'multipath_id' in device_info:
            multipath_id = device_info['multipath_id']
            mdev_info = self._linuxscsi.find_multipath_device(multipath_id)
            devices = mdev_info['devices']
            LOG.debug("devices to remove = %s" % devices)

        # There may have been more than 1 device mounted
        # by the kernel for this volume.  We have to remove
        # all of them
        for device in devices:
            self._linuxscsi.remove_scsi_device(device["device"])

    def _get_pci_num(self, hba):
        # NOTE(walter-boring)
        # device path is in format of
        # /sys/devices/pci0000:00/0000:00:03.0/0000:05:00.3/host2/fc_host/host2
        # sometimes an extra entry exists before the host2 value
        # we always want the value prior to the host2 value
        pci_num = None
        if hba is not None:
            if "device_path" in hba:
                index = 0
                device_path = hba['device_path'].split('/')
                for value in device_path:
                    if value.startswith('host'):
                        break
                    index = index + 1

                if index > 0:
                    pci_num = device_path[index - 1]

        return pci_num


class AoEConnector(InitiatorConnector):
    """Connector class to attach/detach AoE volumes."""
    def __init__(self, root_helper, driver=None,
                 execute=putils.execute,
                 device_scan_attempts=DEVICE_SCAN_ATTEMPTS_DEFAULT,
                 *args, **kwargs):
        super(AoEConnector, self).__init__(root_helper, driver=driver,
                                           execute=execute,
                                           device_scan_attempts=
                                           device_scan_attempts,
                                           *args, **kwargs)

    def _get_aoe_info(self, connection_properties):
        shelf = connection_properties['target_shelf']
        lun = connection_properties['target_lun']
        aoe_device = 'e%(shelf)s.%(lun)s' % {'shelf': shelf,
                                             'lun': lun}
        aoe_path = '/dev/etherd/%s' % (aoe_device)
        return aoe_device, aoe_path

    @lockutils.synchronized('aoe_control', 'aoe-')
    def connect_volume(self, connection_properties):
        """Discover and attach the volume.

        connection_properties for AoE must include:
        target_shelf - shelf id of volume
        target_lun - lun id of volume
        """
        aoe_device, aoe_path = self._get_aoe_info(connection_properties)

        device_info = {
            'type': 'block',
            'device': aoe_device,
            'path': aoe_path,
        }

        if os.path.exists(aoe_path):
            self._aoe_revalidate(aoe_device)
        else:
            self._aoe_discover()

        waiting_status = {'tries': 0}

        #NOTE(jbr_): Device path is not always present immediately
        def _wait_for_discovery(aoe_path):
            if os.path.exists(aoe_path):
                raise loopingcall.LoopingCallDone

            if waiting_status['tries'] >= self.device_scan_attempts:
                raise exception.VolumeDeviceNotFound(device=aoe_path)

            LOG.warn(_("AoE volume not yet found at: %(path)s. "
                       "Try number: %(tries)s"),
                     {'path': aoe_device,
                      'tries': waiting_status['tries']})

            self._aoe_discover()
            waiting_status['tries'] += 1

        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_discovery,
                                                     aoe_path)
        timer.start(interval=2).wait()

        if waiting_status['tries']:
            LOG.debug(_("Found AoE device %(path)s "
                        "(after %(tries)s rediscover)"),
                      {'path': aoe_path,
                       'tries': waiting_status['tries']})

        return device_info

    @lockutils.synchronized('aoe_control', 'aoe-')
    def disconnect_volume(self, connection_properties, device_info):
        """Detach and flush the volume.

        connection_properties for AoE must include:
        target_shelf - shelf id of volume
        target_lun - lun id of volume
        """
        aoe_device, aoe_path = self._get_aoe_info(connection_properties)

        if os.path.exists(aoe_path):
            self._aoe_flush(aoe_device)

    def _aoe_discover(self):
        (out, err) = self._execute('aoe-discover',
                                   run_as_root=True,
                                   root_helper=self._root_helper,
                                   check_exit_code=0)

        LOG.debug(_('aoe-discover: stdout=%(out)s stderr%(err)s') %
                  {'out': out, 'err': err})

    def _aoe_revalidate(self, aoe_device):
        (out, err) = self._execute('aoe-revalidate',
                                   aoe_device,
                                   run_as_root=True,
                                   root_helper=self._root_helper,
                                   check_exit_code=0)

        LOG.debug(_('aoe-revalidate %(dev)s: stdout=%(out)s stderr%(err)s') %
                  {'dev': aoe_device, 'out': out, 'err': err})

    def _aoe_flush(self, aoe_device):
        (out, err) = self._execute('aoe-flush',
                                   aoe_device,
                                   run_as_root=True,
                                   root_helper=self._root_helper,
                                   check_exit_code=0)
        LOG.debug(_('aoe-flush %(dev)s: stdout=%(out)s stderr%(err)s') %
                  {'dev': aoe_device, 'out': out, 'err': err})


class RemoteFsConnector(InitiatorConnector):
    """Connector class to attach/detach NFS and GlusterFS volumes."""

    def __init__(self, mount_type, root_helper, driver=None,
                 execute=putils.execute,
                 device_scan_attempts=DEVICE_SCAN_ATTEMPTS_DEFAULT,
                 *args, **kwargs):
        kwargs = kwargs or {}
        conn = kwargs.get('conn')
        if conn:
            mount_point_base = conn.get('mount_point_base')
            if mount_type.lower() == 'nfs':
                kwargs['nfs_mount_point_base'] =\
                    kwargs.get('nfs_mount_point_base') or\
                    mount_point_base
            elif mount_type.lower() == 'glusterfs':
                kwargs['glusterfs_mount_point_base'] =\
                    kwargs.get('glusterfs_mount_point_base') or\
                    mount_point_base
        else:
            LOG.warn(_("Connection details not present."
                       " RemoteFsClient may not initialize properly."))
        self._remotefsclient = remotefs.RemoteFsClient(mount_type, root_helper,
                                                       execute=execute,
                                                       *args, **kwargs)
        super(RemoteFsConnector, self).__init__(root_helper, driver=driver,
                                                execute=execute,
                                                device_scan_attempts=
                                                device_scan_attempts,
                                                *args, **kwargs)

    def set_execute(self, execute):
        super(RemoteFsConnector, self).set_execute(execute)
        self._remotefsclient.set_execute(execute)

    def connect_volume(self, connection_properties):
        """Ensure that the filesystem containing the volume is mounted.

        connection_properties must include:
        export - remote filesystem device (e.g. '172.18.194.100:/var/nfs')
        name - file name within the filesystem

        connection_properties may optionally include:
        options - options to pass to mount
        """

        mnt_flags = []
        if connection_properties.get('options'):
            mnt_flags = connection_properties['options'].split()

        nfs_share = connection_properties['export']
        self._remotefsclient.mount(nfs_share, mnt_flags)
        mount_point = self._remotefsclient.get_mount_point(nfs_share)

        path = mount_point + '/' + connection_properties['name']

        return {'path': path}

    def disconnect_volume(self, connection_properties, device_info):
        """No need to do anything to disconnect a volume in a filesystem."""


class LocalConnector(InitiatorConnector):
    """"Connector class to attach/detach File System backed volumes."""

    def __init__(self, root_helper, driver=None, execute=putils.execute,
                 *args, **kwargs):
        super(LocalConnector, self).__init__(root_helper, driver=driver,
                                             execute=execute, *args, **kwargs)

    def connect_volume(self, connection_properties):
        """Connect to a volume.

        connection_properties must include:
        device_path - path to the volume to be connected
        """
        if 'device_path' not in connection_properties:
            msg = (_("Invalid connection_properties specified "
                     "no device_path attribute"))
            raise ValueError(msg)

        device_info = {'type': 'local',
                       'path': connection_properties['device_path']}
        return device_info

    def disconnect_volume(self, connection_properties, device_info):
        """Disconnect a volume from the local host."""
        pass
