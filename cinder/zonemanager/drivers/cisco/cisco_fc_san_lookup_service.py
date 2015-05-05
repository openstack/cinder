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


import random

from eventlet import greenthread
from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_utils import excutils
import six

from cinder import exception
from cinder.i18n import _, _LE
from cinder import ssh_utils
from cinder import utils
from cinder.zonemanager.drivers.cisco import cisco_fabric_opts as fabric_opts
import cinder.zonemanager.drivers.cisco.fc_zone_constants as zone_constant
from cinder.zonemanager import fc_san_lookup_service as fc_service
from cinder.zonemanager import utils as zm_utils

LOG = logging.getLogger(__name__)


class CiscoFCSanLookupService(fc_service.FCSanLookupService):
    """The SAN lookup service that talks to Cisco switches.

    Version History:
        1.0.0 - Initial version

    """

    VERSION = "1.0.0"

    def __init__(self, **kwargs):
        """Initializing the client."""
        super(CiscoFCSanLookupService, self).__init__(**kwargs)
        self.configuration = kwargs.get('configuration', None)
        self.create_configuration()

        self.switch_user = ""
        self.switch_port = ""
        self.switch_pwd = ""
        self.switch_ip = ""
        self.sshpool = None

    def create_configuration(self):
        """Configuration specific to SAN context values."""
        config = self.configuration

        fabric_names = [x.strip() for x in config.fc_fabric_names.split(',')]
        LOG.debug('Fabric Names: %s', fabric_names)

        # There can be more than one SAN in the network and we need to
        # get credentials for each for SAN context lookup later.
        # Cisco Zonesets require VSANs
        if fabric_names:
            self.fabric_configs = fabric_opts.load_fabric_configurations(
                fabric_names)

    def get_device_mapping_from_network(self,
                                        initiator_wwn_list,
                                        target_wwn_list):
        """Provides the initiator/target map for available SAN contexts.

        Looks up fcns database of each fc SAN configured to find logged in
        devices and returns a map of initiator and target port WWNs for each
        fabric.

        :param initiator_wwn_list: List of initiator port WWN
        :param target_wwn_list: List of target port WWN
        :returns List -- device wwn map in following format
            {
                <San name>: {
                    'initiator_port_wwn_list':
                    ('200000051e55a100', '200000051e55a121'..)
                    'target_port_wwn_list':
                    ('100000051e55a100', '100000051e55a121'..)
                }
            }
        :raises Exception when connection to fabric is failed
        """
        device_map = {}
        formatted_target_list = []
        formatted_initiator_list = []
        fabric_map = {}
        fabric_names = self.configuration.fc_fabric_names

        if not fabric_names:
            raise exception.InvalidParameterValue(
                err=_("Missing Fibre Channel SAN configuration "
                      "param - fc_fabric_names"))

        fabrics = [x.strip() for x in fabric_names.split(',')]

        LOG.debug("FC Fabric List: %s", fabrics)
        if fabrics:
            for t in target_wwn_list:
                formatted_target_list.append(zm_utils.get_formatted_wwn(t))

            for i in initiator_wwn_list:
                formatted_initiator_list.append(zm_utils.get_formatted_wwn(i))

            for fabric_name in fabrics:
                self.switch_ip = self.fabric_configs[fabric_name].safe_get(
                    'cisco_fc_fabric_address')
                self.switch_user = self.fabric_configs[fabric_name].safe_get(
                    'cisco_fc_fabric_user')
                self.switch_pwd = self.fabric_configs[fabric_name].safe_get(
                    'cisco_fc_fabric_password')
                self.switch_port = self.fabric_configs[fabric_name].safe_get(
                    'cisco_fc_fabric_port')
                zoning_vsan = self.fabric_configs[fabric_name].safe_get(
                    'cisco_zoning_vsan')

                # Get name server data from fabric and find the targets
                # logged in
                nsinfo = ''
                LOG.debug("show fcns database for vsan %s", zoning_vsan)
                nsinfo = self.get_nameserver_info(zoning_vsan)

                LOG.debug("Lookup service:fcnsdatabase-%s", nsinfo)
                LOG.debug("Lookup service:initiator list from caller-%s",
                          formatted_initiator_list)
                LOG.debug("Lookup service:target list from caller-%s",
                          formatted_target_list)
                visible_targets = filter(lambda x: x in formatted_target_list,
                                         nsinfo)
                visible_initiators = filter(lambda x: x in
                                            formatted_initiator_list, nsinfo)

                if visible_targets:
                    LOG.debug("Filtered targets is: %s", visible_targets)
                    # getting rid of the : before returning
                    for idx, elem in enumerate(visible_targets):
                        elem = str(elem).replace(':', '')
                        visible_targets[idx] = elem
                else:
                    LOG.debug("No targets are in the fcns database"
                              " for vsan %s", zoning_vsan)

                if visible_initiators:
                    # getting rid of the : before returning ~sk
                    for idx, elem in enumerate(visible_initiators):
                        elem = str(elem).replace(':', '')
                        visible_initiators[idx] = elem
                else:
                    LOG.debug("No initiators are in the fcns database"
                              " for vsan %s", zoning_vsan)

                fabric_map = {'initiator_port_wwn_list': visible_initiators,
                              'target_port_wwn_list': visible_targets
                              }
                device_map[zoning_vsan] = fabric_map
        LOG.debug("Device map for SAN context: %s", device_map)
        return device_map

    def get_nameserver_info(self, fabric_vsan):
        """Get fcns database info from fabric.

        This method will return the connected node port wwn list(local
        and remote) for the given switch fabric
        """
        cli_output = None
        nsinfo_list = []
        try:
            cmd = ([zone_constant.FCNS_SHOW, fabric_vsan, ' | no-more'])
            cli_output = self._get_switch_info(cmd)
        except exception.FCSanLookupServiceException:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Failed collecting show fcns database for"
                              " fabric"))
        if cli_output:
            nsinfo_list = self._parse_ns_output(cli_output)

        LOG.debug("Connector returning fcns info-%s", nsinfo_list)
        return nsinfo_list

    def _get_switch_info(self, cmd_list):
        stdout, stderr, sw_data = None, None, None
        try:
            stdout, stderr = self._run_ssh(cmd_list, True, 1)
            LOG.debug("CLI output from ssh - output: %s", stdout)
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

        :returns list of device port wwn from ns info
        """
        nsinfo_list = []
        for line in switch_data:
            if not(" N " in line):
                continue
            linesplit = line.split()
            if len(linesplit) > 2:
                node_port_wwn = linesplit[2]
                nsinfo_list.append(node_port_wwn)
            else:
                msg = _("Malformed fcns output string: %s") % line
                LOG.error(msg)
                raise exception.InvalidParameterValue(err=msg)
        return nsinfo_list

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
                LOG.error(_LE("Error running SSH command: %s"), command)

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
        LOG.debug("Executing command via ssh: %s", command)
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
