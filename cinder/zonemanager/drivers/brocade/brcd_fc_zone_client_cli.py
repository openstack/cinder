#    (c) Copyright 2014 Brocade Communications Systems Inc.
#    All Rights Reserved.
#
#    Copyright 2014 OpenStack Foundation
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
#


"""
Script to push the zone configuration to brocade SAN switches.
"""

import random
import re

from eventlet import greenthread
from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_utils import excutils
import six

from cinder import exception
from cinder.i18n import _, _LE
from cinder import ssh_utils
from cinder import utils
import cinder.zonemanager.drivers.brocade.fc_zone_constants as ZoneConstant

LOG = logging.getLogger(__name__)


class BrcdFCZoneClientCLI(object):
    switch_ip = None
    switch_port = '22'
    switch_user = 'admin'
    switch_pwd = 'none'
    patrn = re.compile('[;\s]+')

    def __init__(self, ipaddress, username, password, port):
        """initializing the client."""
        self.switch_ip = ipaddress
        self.switch_port = port
        self.switch_user = username
        self.switch_pwd = password
        self.sshpool = None

    def get_active_zone_set(self):
        """Return the active zone configuration.

        Return active zoneset from fabric. When none of the configurations
        are active then it will return empty map.

        :returns: Map -- active zone set map in the following format
        {
            'zones':
                {'openstack50060b0000c26604201900051ee8e329':
                    ['50060b0000c26604', '201900051ee8e329']
                },
            'active_zone_config': 'OpenStack_Cfg'
        }
        """
        zone_set = {}
        zone = {}
        zone_member = None
        zone_name = None
        switch_data = None
        zone_set_name = None
        try:
            switch_data = self._get_switch_info(
                [ZoneConstant.GET_ACTIVE_ZONE_CFG])
        except exception.BrocadeZoningCliException:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Failed getting active zone set "
                              "from fabric %s"), self.switch_ip)
        try:
            for line in switch_data:
                line_split = re.split('\\t', line)
                if len(line_split) > 2:
                    line_split = [x.replace(
                        '\n', '') for x in line_split]
                    line_split = [x.replace(
                        ' ',
                        '') for x in line_split]
                    if ZoneConstant.CFG_ZONESET in line_split:
                        zone_set_name = line_split[1]
                        continue
                    if line_split[1]:
                        zone_name = line_split[1]
                        zone[zone_name] = list()
                    if line_split[2]:
                        zone_member = line_split[2]
                        zone_member_list = zone.get(zone_name)
                        zone_member_list.append(zone_member)
            zone_set[ZoneConstant.CFG_ZONES] = zone
            zone_set[ZoneConstant.ACTIVE_ZONE_CONFIG] = zone_set_name
        except Exception:
            # Incase of parsing error here, it should be malformed cli output.
            msg = _("Malformed zone configuration: (switch=%(switch)s "
                    "zone_config=%(zone_config)s)."
                    ) % {'switch': self.switch_ip,
                         'zone_config': switch_data}
            LOG.exception(msg)
            raise exception.FCZoneDriverException(reason=msg)
        switch_data = None
        return zone_set

    def add_zones(self, zones, activate, active_zone_set=None):
        """Add zone configuration.

        This method will add the zone configuration passed by user.
            input params:
            zones - zone names mapped to members.
            zone members are colon separated but case-insensitive
            {   zonename1:[zonememeber1,zonemember2,...],
                zonename2:[zonemember1, zonemember2,...]...}
            e.g: {'openstack50060b0000c26604201900051ee8e329':
                    ['50:06:0b:00:00:c2:66:04', '20:19:00:05:1e:e8:e3:29']
                }
            activate - True/False
            active_zone_set - active zone set dict retrieved from
                              get_active_zone_set method
        """
        LOG.debug("Add Zones - Zones passed: %s", zones)
        cfg_name = None
        iterator_count = 0
        zone_with_sep = ''
        if not active_zone_set:
            active_zone_set = self.get_active_zone_set()
            LOG.debug("Active zone set: %s", active_zone_set)
        zone_list = active_zone_set[ZoneConstant.CFG_ZONES]
        LOG.debug("zone list: %s", zone_list)
        for zone in zones.keys():
            # If zone exists, its an update. Delete & insert
            # TODO(skolathur): This still need to be optimized
            # to an update call later. Now we just handled the
            # same zone name with same zone members.
            if (zone in zone_list):
                if set(zones[zone]) == set(zone_list[zone]):
                    break
                try:
                    self.delete_zones(zone, activate, active_zone_set)
                except exception.BrocadeZoningCliException:
                    with excutils.save_and_reraise_exception():
                        LOG.error(_LE("Deleting zone failed %s"), zone)
                LOG.debug("Deleted Zone before insert : %s", zone)
            zone_members_with_sep = ';'.join(str(member) for
                                             member in zones[zone])
            LOG.debug("Forming command for add zone")
            cmd = 'zonecreate "%(zone)s", "%(zone_members_with_sep)s"' % {
                'zone': zone,
                'zone_members_with_sep': zone_members_with_sep}
            LOG.debug("Adding zone, cmd to run %s", cmd)
            self.apply_zone_change(cmd.split())
            LOG.debug("Created zones on the switch")
            if(iterator_count > 0):
                zone_with_sep += ';'
            iterator_count += 1
            zone_with_sep += zone
        if not zone_with_sep:
            return
        try:
            # Get active zone set from device, as some of the zones
            # could be deleted.
            active_zone_set = self.get_active_zone_set()
            cfg_name = active_zone_set[ZoneConstant.ACTIVE_ZONE_CONFIG]
            cmd = None
            if not cfg_name:
                cfg_name = ZoneConstant.OPENSTACK_CFG_NAME
                cmd = 'cfgcreate "%(zoneset)s", "%(zones)s"' \
                    % {'zoneset': cfg_name, 'zones': zone_with_sep}
            else:
                cmd = 'cfgadd "%(zoneset)s", "%(zones)s"' \
                    % {'zoneset': cfg_name, 'zones': zone_with_sep}
            LOG.debug("New zone %s", cmd)
            self.apply_zone_change(cmd.split())
            if activate:
                self.activate_zoneset(cfg_name)
            else:
                self._cfg_save()
        except Exception as e:
            self._cfg_trans_abort()
            msg = _("Creating and activating zone set failed: "
                    "(Zone set=%(cfg_name)s error=%(err)s)."
                    ) % {'cfg_name': cfg_name, 'err': six.text_type(e)}
            LOG.error(msg)
            raise exception.BrocadeZoningCliException(reason=msg)

    def activate_zoneset(self, cfgname):
        """Method to Activate the zone config. Param cfgname - ZonesetName."""
        cmd_list = [ZoneConstant.ACTIVATE_ZONESET, cfgname]
        return self._ssh_execute(cmd_list, True, 1)

    def deactivate_zoneset(self):
        """Method to deActivate the zone config."""
        return self._ssh_execute([ZoneConstant.DEACTIVATE_ZONESET], True, 1)

    def delete_zones(self, zone_names, activate, active_zone_set=None):
        """Delete zones from fabric.

        Method to delete the active zone config zones

        params zone_names: zoneNames separated by semicolon
        params activate: True/False
        params active_zone_set: the active zone set dict retrieved
                                from get_active_zone_set method
        """
        active_zoneset_name = None
        zone_list = []
        if not active_zone_set:
            active_zone_set = self.get_active_zone_set()
        active_zoneset_name = active_zone_set[
            ZoneConstant.ACTIVE_ZONE_CONFIG]
        zone_list = active_zone_set[ZoneConstant.CFG_ZONES]
        zones = self.patrn.split(''.join(zone_names))
        cmd = None
        try:
            if len(zones) == len(zone_list):
                self.deactivate_zoneset()
                cmd = 'cfgdelete "%(active_zoneset_name)s"' \
                    % {'active_zoneset_name': active_zoneset_name}
                # Active zoneset is being deleted, hence reset activate flag
                activate = False
            else:
                cmd = 'cfgremove "%(active_zoneset_name)s", "%(zone_names)s"' \
                    % {'active_zoneset_name': active_zoneset_name,
                       'zone_names': zone_names
                       }
            LOG.debug("Delete zones: Config cmd to run: %s", cmd)
            self.apply_zone_change(cmd.split())
            for zone in zones:
                self._zone_delete(zone)
            if activate:
                self.activate_zoneset(active_zoneset_name)
            else:
                self._cfg_save()
        except Exception as e:
            msg = _("Deleting zones failed: (command=%(cmd)s error=%(err)s)."
                    ) % {'cmd': cmd, 'err': six.text_type(e)}
            LOG.error(msg)
            self._cfg_trans_abort()
            raise exception.BrocadeZoningCliException(reason=msg)

    def get_nameserver_info(self):
        """Get name server data from fabric.

        This method will return the connected node port wwn list(local
        and remote) for the given switch fabric
        """
        cli_output = None
        return_list = []
        try:
            cmd = '%(nsshow)s;%(nscamshow)s' % {
                'nsshow': ZoneConstant.NS_SHOW,
                'nscamshow': ZoneConstant.NS_CAM_SHOW}
            cli_output = self._get_switch_info([cmd])
        except exception.BrocadeZoningCliException:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Failed collecting nsshow "
                              "info for fabric %s"), self.switch_ip)
        if (cli_output):
            return_list = self._parse_ns_output(cli_output)
        cli_output = None
        return return_list

    def _cfg_save(self):
        self._ssh_execute([ZoneConstant.CFG_SAVE], True, 1)

    def _zone_delete(self, zone_name):
        cmd = 'zonedelete "%(zone_name)s"' % {'zone_name': zone_name}
        self.apply_zone_change(cmd.split())

    def _cfg_trans_abort(self):
        is_abortable = self._is_trans_abortable()
        if(is_abortable):
            self.apply_zone_change([ZoneConstant.CFG_ZONE_TRANS_ABORT])

    def _is_trans_abortable(self):
        is_abortable = False
        stdout, stderr = None, None
        stdout, stderr = self._run_ssh(
            [ZoneConstant.CFG_SHOW_TRANS], True, 1)
        output = stdout.splitlines()
        is_abortable = False
        for line in output:
            if(ZoneConstant.TRANS_ABORTABLE in line):
                is_abortable = True
                break
        if stderr:
            msg = _("Error while checking transaction status: %s") % stderr
            raise exception.BrocadeZoningCliException(reason=msg)
        else:
            return is_abortable

    def apply_zone_change(self, cmd_list):
        """Execute zoning cli with no status update.

        Executes CLI commands such as addZone where status return is
        not expected.
        """
        stdout, stderr = None, None
        LOG.debug("Executing command via ssh: %s", cmd_list)
        stdout, stderr = self._run_ssh(cmd_list, True, 1)
        # no output expected, so output means there is an error
        if stdout:
            msg = _("Error while running zoning CLI: (command=%(cmd)s "
                    "error=%(err)s).") % {'cmd': cmd_list, 'err': stdout}
            LOG.error(msg)
            self._cfg_trans_abort()
            raise exception.BrocadeZoningCliException(reason=msg)

    def is_supported_firmware(self):
        """Check firmware version is v6.4 or higher.

        This API checks if the firmware version per the plug-in support level.
        This only checks major and minor version.
        """
        cmd = ['version']
        firmware = 0
        try:
            stdout, stderr = self._execute_shell_cmd(cmd)
            if (stdout):
                for line in stdout:
                    if 'Fabric OS:  v' in line:
                        LOG.debug("Firmware version string: %s", line)
                        ver = line.split('Fabric OS:  v')[1].split('.')
                        if (ver):
                            firmware = int(ver[0] + ver[1])
                return firmware > 63
            else:
                LOG.error(_LE("No CLI output for firmware version check"))
                return False
        except processutils.ProcessExecutionError as e:
            msg = _("Error while getting data via ssh: (command=%(cmd)s "
                    "error=%(err)s).") % {'cmd': cmd, 'err': six.text_type(e)}
            LOG.error(msg)
            raise exception.BrocadeZoningCliException(reason=msg)

    def _get_switch_info(self, cmd_list):
        stdout, stderr, sw_data = None, None, None
        try:
            stdout, stderr = self._run_ssh(cmd_list, True, 1)
            if (stdout):
                sw_data = stdout.splitlines()
            return sw_data
        except processutils.ProcessExecutionError as e:
            msg = _("Error while getting data via ssh: (command=%(cmd)s "
                    "error=%(err)s).") % {'cmd': cmd_list,
                                          'err': six.text_type(e)}
            LOG.error(msg)
            raise exception.BrocadeZoningCliException(reason=msg)

    def _parse_ns_output(self, switch_data):
        """Parses name server data.

        Parses nameserver raw data and adds the device port wwns to the list

        :returns: List -- list of device port wwn from ns info
        """
        return_list = []
        for line in switch_data:
            if not(" NL " in line or " N " in line):
                continue
            linesplit = line.split(';')
            if len(linesplit) > 2:
                node_port_wwn = linesplit[2]
                return_list.append(node_port_wwn)
            else:
                msg = _("Malformed nameserver string: %s") % line
                LOG.error(msg)
                raise exception.InvalidParameterValue(err=msg)
        return return_list

    def _run_ssh(self, cmd_list, check_exit_code=True, attempts=1):
        # TODO(skolathur): Need to implement ssh_injection check
        # currently, the check will fail for zonecreate command
        # as zone members are separated by ';'which is a danger char
        command = ' '. join(cmd_list)

        if not self.sshpool:
            self.sshpool = ssh_utils.SSHPool(self.switch_ip,
                                             self.switch_port,
                                             None,
                                             self.switch_user,
                                             self.switch_pwd,
                                             min_size=1,
                                             max_size=5)
        last_exception = None
        try:
            with self.sshpool.item() as ssh:
                while attempts > 0:
                    attempts -= 1
                    try:
                        return processutils.ssh_execute(
                            ssh,
                            command,
                            check_exit_code=check_exit_code)
                    except Exception as e:
                        LOG.exception(_LE('Error executing SSH command.'))
                        last_exception = e
                        greenthread.sleep(random.randint(20, 500) / 100.0)
                try:
                    raise processutils.ProcessExecutionError(
                        exit_code=last_exception.exit_code,
                        stdout=last_exception.stdout,
                        stderr=last_exception.stderr,
                        cmd=last_exception.cmd)
                except AttributeError:
                    raise processutils.ProcessExecutionError(
                        exit_code=-1,
                        stdout="",
                        stderr="Error running SSH command",
                        cmd=command)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Error running SSH command: %s"), command)

    def _ssh_execute(self, cmd_list, check_exit_code=True, attempts=1):
        """Execute cli with status update.

        Executes CLI commands such as cfgsave where status return is expected.
        """
        utils.check_ssh_injection(cmd_list)
        command = ' '. join(cmd_list)

        if not self.sshpool:
            self.sshpool = ssh_utils.SSHPool(self.switch_ip,
                                             self.switch_port,
                                             None,
                                             self.switch_user,
                                             self.switch_pwd,
                                             min_size=1,
                                             max_size=5)
        stdin, stdout, stderr = None, None, None
        LOG.debug("Executing command via ssh: %s", command)
        last_exception = None
        try:
            with self.sshpool.item() as ssh:
                while attempts > 0:
                    attempts -= 1
                    try:
                        stdin, stdout, stderr = ssh.exec_command(command)
                        stdin.write("%s\n" % ZoneConstant.YES)
                        channel = stdout.channel
                        exit_status = channel.recv_exit_status()
                        LOG.debug("Exit Status from ssh: %s", exit_status)
                        # exit_status == -1 if no exit code was returned
                        if exit_status != -1:
                            LOG.debug('Result was %s', exit_status)
                            if check_exit_code and exit_status != 0:
                                raise processutils.ProcessExecutionError(
                                    exit_code=exit_status,
                                    stdout=stdout,
                                    stderr=stderr,
                                    cmd=command)
                            else:
                                return True
                        else:
                            return True
                    except Exception as e:
                        LOG.exception(_LE('Error executing SSH command.'))
                        last_exception = e
                        greenthread.sleep(random.randint(20, 500) / 100.0)
                LOG.debug("Handling error case after "
                          "SSH: %s", last_exception)
                try:
                    raise processutils.ProcessExecutionError(
                        exit_code=last_exception.exit_code,
                        stdout=last_exception.stdout,
                        stderr=last_exception.stderr,
                        cmd=last_exception.cmd)
                except AttributeError:
                    raise processutils.ProcessExecutionError(
                        exit_code=-1,
                        stdout="",
                        stderr="Error running SSH command",
                        cmd=command)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Error executing command via ssh: %s"), e)
        finally:
            if stdin:
                stdin.flush()
                stdin.close()
            if stdout:
                stdout.close()
            if stderr:
                stderr.close()

    def _execute_shell_cmd(self, cmd):
        """Run command over shell for older firmware versions.

        We invoke shell and issue the command and return the output.
        This is primarily used for issuing read commands when we are not sure
        if the firmware supports exec_command.
        """
        utils.check_ssh_injection(cmd)
        command = ' '. join(cmd)
        stdout, stderr = None, None
        if not self.sshpool:
            self.sshpool = ssh_utils.SSHPool(self.switch_ip,
                                             self.switch_port,
                                             None,
                                             self.switch_user,
                                             self.switch_pwd,
                                             min_size=1,
                                             max_size=5)
        with self.sshpool.item() as ssh:
            LOG.debug('Running cmd (SSH): %s', command)
            channel = ssh.invoke_shell()
            stdin_stream = channel.makefile('wb')
            stdout_stream = channel.makefile('rb')
            stderr_stream = channel.makefile('rb')
            stdin_stream.write('''%s
exit
''' % command)
            stdin_stream.flush()
            stdout = stdout_stream.readlines()
            stderr = stderr_stream.readlines()
            stdin_stream.close()
            stdout_stream.close()
            stderr_stream.close()

            exit_status = channel.recv_exit_status()
            # exit_status == -1 if no exit code was returned
            if exit_status != -1:
                LOG.debug('Result was %s', exit_status)
                if exit_status != 0:
                    LOG.debug("command %s failed", command)
                    raise processutils.ProcessExecutionError(
                        exit_code=exit_status,
                        stdout=stdout,
                        stderr=stderr,
                        cmd=command)
            try:
                channel.close()
            except Exception:
                LOG.exception(_LE('Error closing channel.'))
            LOG.debug("_execute_cmd: stderr to return: %s", stderr)
        return (stdout, stderr)

    def cleanup(self):
        self.sshpool = None
