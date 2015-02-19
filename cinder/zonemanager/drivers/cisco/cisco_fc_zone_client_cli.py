#    (c) Copyright 2014 Cisco Systems Inc.
#    All Rights Reserved.
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
Script to push the zone configuration to Cisco SAN switches.
"""
import random
import re

from eventlet import greenthread
from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_utils import excutils
import six

from cinder import exception
from cinder.i18n import _, _LE, _LI
from cinder import ssh_utils
from cinder import utils
import cinder.zonemanager.drivers.cisco.fc_zone_constants as ZoneConstant

LOG = logging.getLogger(__name__)


class CiscoFCZoneClientCLI(object):
    """Cisco FC zone client cli implementation.

    OpenStack Fibre Channel zone client cli connector
    to manage FC zoning in Cisco SAN fabrics.

    Version history:
        1.0 - Initial Cisco FC zone client cli
    """

    switch_ip = None
    switch_port = '22'
    switch_user = 'admin'
    switch_pwd = 'none'

    def __init__(self, ipaddress, username, password, port, vsan):
        """initializing the client."""
        self.switch_ip = ipaddress
        self.switch_port = port
        self.switch_user = username
        self.switch_pwd = password
        self.fabric_vsan = vsan
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
                [ZoneConstant.GET_ACTIVE_ZONE_CFG, self.fabric_vsan,
                 ' | no-more'])
        except exception.CiscoZoningCliException:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Failed getting active zone set "
                              "from fabric %s"), self.switch_ip)
        try:
            for line in switch_data:
                # Split on non-word characters,
                line_split = re.split('[\s\[\]]+', line)
                if ZoneConstant.CFG_ZONESET in line_split:
                    # zoneset name [name] vsan [vsan]
                    zone_set_name = \
                        line_split[line_split.index(ZoneConstant.CFG_ZONESET)
                                   + 2]
                    continue
                if ZoneConstant.CFG_ZONE in line_split:
                    # zone name [name] vsan [vsan]
                    zone_name = \
                        line_split[line_split.index(ZoneConstant.CFG_ZONE) + 2]
                    zone[zone_name] = list()
                    continue
                if ZoneConstant.CFG_ZONE_MEMBER in line_split:
                    # Examples:
                    # pwwn c0:50:76:05:15:9f:00:12
                    # * fcid 0x1e01c0 [pwwn 50:05:07:68:02:20:48:04] [V7K_N1P2]
                    zone_member = \
                        line_split[
                            line_split.index(ZoneConstant.CFG_ZONE_MEMBER) + 1]
                    zone_member_list = zone.get(zone_name)
                    zone_member_list.append(zone_member)

            zone_set[ZoneConstant.CFG_ZONES] = zone
            zone_set[ZoneConstant.ACTIVE_ZONE_CONFIG] = zone_set_name
        except Exception as ex:
            # In case of parsing error here, it should be malformed cli output.
            msg = _("Malformed zone configuration: (switch=%(switch)s "
                    "zone_config=%(zone_config)s)."
                    ) % {'switch': self.switch_ip,
                         'zone_config': switch_data}
            LOG.error(msg)
            exc_msg = _("Exception: %s") % six.text_type(ex)
            LOG.exception(exc_msg)
            raise exception.FCZoneDriverException(reason=msg)

        return zone_set

    def add_zones(self, zones, activate, fabric_vsan, active_zone_set,
                  zone_status):
        """Add zone configuration.

        This method will add the zone configuration passed by user.
            input params:
            zones - zone names mapped to members and VSANs.
            zone members are colon separated but case-insensitive
            {   zonename1:[zonememeber1,zonemember2,...],
                zonename2:[zonemember1, zonemember2,...]...}
            e.g: {'openstack50060b0000c26604201900051ee8e329':
                    ['50:06:0b:00:00:c2:66:04', '20:19:00:05:1e:e8:e3:29']
                }
            activate - True/False
        """
        LOG.debug("Add Zones - Zones passed: %s", zones)

        LOG.debug("Active zone set:%s", active_zone_set)
        zone_list = active_zone_set[ZoneConstant.CFG_ZONES]
        LOG.debug("zone list:%s", zone_list)
        LOG.debug("zone status:%s", zone_status)

        cfg_name = active_zone_set[ZoneConstant.ACTIVE_ZONE_CONFIG]

        zone_cmds = [['conf'],
                     ['zoneset', 'name', cfg_name, 'vsan', fabric_vsan]]

        for zone in zones.keys():
            # if zone exists, its an update. Delete & insert
            LOG.debug("Update call")
            if zone in zone_list:
                # Response from get_active_zone_set strips colons from WWPNs
                current_zone = set(zone_list[zone])
                new_wwpns = map(lambda x: x.lower().replace(':', ''),
                                zones[zone])
                new_zone = set(new_wwpns)

                if current_zone != new_zone:
                    try:
                        self.delete_zones([zone], activate, fabric_vsan,
                                          active_zone_set, zone_status)
                    except exception.CiscoZoningCliException:
                        with excutils.save_and_reraise_exception():
                            LOG.error(_LE("Deleting zone failed %s"), zone)
                    LOG.debug("Deleted Zone before insert : %s", zone)

            zone_cmds.append(['zone', 'name', zone])

            for member in zones[zone]:
                zone_cmds.append(['member', 'pwwn', member])

        zone_cmds.append(['end'])

        try:
            LOG.debug("Add zones: Config cmd to run:%s", zone_cmds)
            self._ssh_execute(zone_cmds, True, 1)

            if activate:
                self.activate_zoneset(cfg_name, fabric_vsan, zone_status)
            self._cfg_save()
        except Exception as e:

            msg = _("Creating and activating zone set failed: "
                    "(Zone set=%(zoneset)s error=%(err)s)."
                    ) % {'zoneset': cfg_name, 'err': six.text_type(e)}
            LOG.error(msg)
            raise exception.CiscoZoningCliException(reason=msg)

    def activate_zoneset(self, cfgname, fabric_vsan, zone_status):
        """Method to Activate the zone config. Param cfgname - ZonesetName."""

        LOG.debug("zone status:%s", zone_status)

        cmd_list = [['conf'],
                    ['zoneset', 'activate', 'name', cfgname, 'vsan',
                     self.fabric_vsan]]
        if zone_status['mode'] == 'enhanced':
            cmd_list.append(['zone', 'commit', 'vsan', fabric_vsan])

        cmd_list.append(['end'])

        return self._ssh_execute(cmd_list, True, 1)

    def get_zoning_status(self):
        """Return the zoning mode and session for a zoneset."""
        zone_status = {}

        try:
            switch_data = self._get_switch_info(
                [ZoneConstant.GET_ZONE_STATUS, self.fabric_vsan])
        except exception.CiscoZoningCliException:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Failed getting zone status "
                              "from fabric %s"), self.switch_ip)
        try:
            for line in switch_data:
                # Split on non-word characters,
                line_split = re.split('[\s\[\]]+', line)
                if 'mode:' in line_split:
                    # mode: <enhanced|basic>
                    zone_status['mode'] = line_split[line_split.index('mode:')
                                                     + 1]
                    continue
                if 'session:' in line_split:
                    # session: <none|a value other than none>
                    zone_status['session'] = \
                        line_split[line_split.index('session:') + 1]
                    continue
        except Exception as ex:
            # In case of parsing error here, it should be malformed cli output.
            msg = _("Malformed zone status: (switch=%(switch)s "
                    "zone_config=%(zone_config)s)."
                    ) % {'switch': self.switch_ip,
                         'zone_status': switch_data}
            LOG.error(msg)
            exc_msg = _("Exception: %s") % six.text_type(ex)
            LOG.exception(exc_msg)
            raise exception.FCZoneDriverException(reason=msg)

        return zone_status

    def delete_zones(self, zone_names, activate, fabric_vsan, active_zone_set,
                     zone_status):
        """Delete zones from fabric.

        Method to delete the active zone config zones

        params zone_names: zoneNames separated by semicolon
        params activate: True/False
        """

        LOG.debug("zone_names %s", zone_names)
        active_zoneset_name = active_zone_set[ZoneConstant.ACTIVE_ZONE_CONFIG]

        cmds = [['conf'],
                ['zoneset', 'name', active_zoneset_name, 'vsan',
                 fabric_vsan]]

        try:
            for zone in set(zone_names.split(';')):
                cmds.append(['no', 'zone', 'name', zone])

            cmds.append(['end'])

            LOG.debug("Delete zones: Config cmd to run:%s", cmds)
            self._ssh_execute(cmds, True, 1)

            if activate:
                self.activate_zoneset(active_zoneset_name, fabric_vsan,
                                      zone_status)
            self._cfg_save()

        except Exception as e:
            msg = _("Deleting zones failed: (command=%(cmd)s error=%(err)s)."
                    ) % {'cmd': cmds, 'err': six.text_type(e)}
            LOG.error(msg)
            raise exception.CiscoZoningCliException(reason=msg)

    def get_nameserver_info(self):
        """Get name server data from fabric.

        This method will return the connected node port wwn list(local
        and remote) for the given switch fabric

        show fcns database
        """
        cli_output = None
        return_list = []
        try:
            cli_output = self._get_switch_info([ZoneConstant.FCNS_SHOW,
                                                self.fabric_vsan])
        except exception.CiscoZoningCliException:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Failed collecting fcns database "
                              "info for fabric %s"), self.switch_ip)

        if (cli_output):
            return_list = self._parse_ns_output(cli_output)

        LOG.info(_LI("Connector returning fcnsinfo-%s"), return_list)

        return return_list

    def _cfg_save(self):
        cmd = ['copy', 'running-config', 'startup-config']
        self._run_ssh(cmd, True, 1)

    def _get_switch_info(self, cmd_list):
        stdout, stderr, sw_data = None, None, None
        try:
            stdout, stderr = self._run_ssh(cmd_list, True, 1)
            LOG.debug("CLI output from ssh - output:%s", stdout)
            if (stdout):
                sw_data = stdout.splitlines()
            return sw_data
        except processutils.ProcessExecutionError as e:
            msg = _("Error while getting data via ssh: (command=%(cmd)s "
                    "error=%(err)s).") % {'cmd': cmd_list,
                                          'err': six.text_type(e)}
            LOG.error(msg)
            raise exception.CiscoZoningCliException(reason=msg)

    def _parse_ns_output(self, switch_data):
        """Parses name server data.

        Parses nameserver raw data and adds the device port wwns to the list

        :returns: List -- list of device port wwn from ns info
        """
        return_list = []
        for line in switch_data:
            if not(" N " in line):
                continue
            linesplit = line.split()
            if len(linesplit) > 2:
                node_port_wwn = linesplit[2]
                return_list.append(node_port_wwn)
            else:
                msg = _("Malformed show fcns database string: %s") % line
                LOG.error(msg)
                raise exception.InvalidParameterValue(err=msg)
        return return_list

    def _run_ssh(self, cmd_list, check_exit_code=True, attempts=1):

        command = ' '.join(cmd_list)

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
                        msg = _("Exception: %s") % six.text_type(e)
                        LOG.error(msg)
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
                LOG.error(_LE("Error running SSH command: %s") % command)

    def _ssh_execute(self, cmd_list, check_exit_code=True, attempts=1):
        """Execute cli with status update.

        Executes CLI commands where status return is expected.

        cmd_list is a list of commands, where each command is itself
        a list of parameters.  We use utils.check_ssh_injection to check each
        command, but then join then with " ; " to form a single command.
        """

        # Check that each command is secure
        for cmd in cmd_list:
            utils.check_ssh_injection(cmd)

        # Combine into a single command.
        command = ' ; '.join(map(lambda x: ' '.join(x), cmd_list))

        if not self.sshpool:
            self.sshpool = ssh_utils.SSHPool(self.switch_ip,
                                             self.switch_port,
                                             None,
                                             self.switch_user,
                                             self.switch_pwd,
                                             min_size=1,
                                             max_size=5)
        stdin, stdout, stderr = None, None, None
        LOG.debug("Executing command via ssh: %s" % command)
        last_exception = None
        try:
            with self.sshpool.item() as ssh:
                while attempts > 0:
                    attempts -= 1
                    try:
                        stdin, stdout, stderr = ssh.exec_command(command)
                        greenthread.sleep(random.randint(20, 500) / 100.0)
                        channel = stdout.channel
                        exit_status = channel.recv_exit_status()
                        LOG.debug("Exit Status from ssh:%s", exit_status)
                        # exit_status == -1 if no exit code was returned
                        if exit_status != -1:
                            LOG.debug('Result was %s' % exit_status)
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
                        msg = _("Exception: %s") % six.text_type(e)
                        LOG.error(msg)
                        last_exception = e
                        greenthread.sleep(random.randint(20, 500) / 100.0)
                LOG.debug("Handling error case after SSH:%s", last_exception)
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
                msg = (_("Error executing command via ssh: %s") %
                       six.text_type(e))
                LOG.error(msg)
        finally:
            if stdin:
                stdin.flush()
                stdin.close()
            if stdout:
                stdout.close()
            if stderr:
                stderr.close()

    def cleanup(self):
        self.sshpool = None
