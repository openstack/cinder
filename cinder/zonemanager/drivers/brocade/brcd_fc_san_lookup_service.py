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


import paramiko

from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import excutils
from cinder.openstack.common import log as logging
from cinder import utils
from cinder.zonemanager.drivers.brocade import brcd_fabric_opts as fabric_opts
import cinder.zonemanager.drivers.brocade.fc_zone_constants as ZoneConstant
from cinder.zonemanager.fc_san_lookup_service import FCSanLookupService

LOG = logging.getLogger(__name__)


class BrcdFCSanLookupService(FCSanLookupService):
    """The SAN lookup service that talks to Brocade switches.

    Version History:
        1.0.0 - Initial version

    """

    VERSION = "1.0.0"

    def __init__(self, **kwargs):
        """Initializing the client."""
        super(BrcdFCSanLookupService, self).__init__(**kwargs)
        self.configuration = kwargs.get('configuration', None)
        self.create_configuration()
        self.client = self.create_ssh_client(**kwargs)

    def create_configuration(self):
        """Configuration specific to SAN context values."""
        config = self.configuration

        fabric_names = [x.strip() for x in config.fc_fabric_names.split(',')]
        LOG.debug('Fabric Names: %s', fabric_names)

        # There can be more than one SAN in the network and we need to
        # get credentials for each for SAN context lookup later.
        if len(fabric_names) > 0:
            self.fabric_configs = fabric_opts.load_fabric_configurations(
                fabric_names)

    def create_ssh_client(self, **kwargs):
        ssh_client = paramiko.SSHClient()
        known_hosts_file = kwargs.get('known_hosts_file', None)
        if known_hosts_file is None:
            ssh_client.load_system_host_keys()
        else:
            ssh_client.load_host_keys(known_hosts_file)
        missing_key_policy = kwargs.get('missing_key_policy', None)
        if missing_key_policy is None:
            missing_key_policy = paramiko.WarningPolicy()
        ssh_client.set_missing_host_key_policy(missing_key_policy)
        return ssh_client

    def get_device_mapping_from_network(self,
                                        initiator_wwn_list,
                                        target_wwn_list):
        """Provides the initiator/target map for available SAN contexts.

        Looks up nameserver of each fc SAN configured to find logged in devices
        and returns a map of initiator and target port WWNs for each fabric.

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
        fabrics = None
        if not fabric_names:
            raise exception.InvalidParameterValue(
                err=_("Missing Fibre Channel SAN configuration "
                      "param - fc_fabric_names"))

        fabrics = [x.strip() for x in fabric_names.split(',')]
        LOG.debug("FC Fabric List: %s", fabrics)
        if fabrics:
            for t in target_wwn_list:
                formatted_target_list.append(self.get_formatted_wwn(t))

            for i in initiator_wwn_list:
                formatted_initiator_list.append(self.
                                                get_formatted_wwn(i))

            for fabric_name in fabrics:
                fabric_ip = self.fabric_configs[fabric_name].safe_get(
                    'fc_fabric_address')
                fabric_user = self.fabric_configs[fabric_name].safe_get(
                    'fc_fabric_user')
                fabric_pwd = self.fabric_configs[fabric_name].safe_get(
                    'fc_fabric_password')
                fabric_port = self.fabric_configs[fabric_name].safe_get(
                    'fc_fabric_port')

                # Get name server data from fabric and find the targets
                # logged in
                nsinfo = ''
                try:
                    LOG.debug("Getting name server data for "
                              "fabric %s", fabric_ip)
                    self.client.connect(
                        fabric_ip, fabric_port, fabric_user, fabric_pwd)
                    nsinfo = self.get_nameserver_info()
                except exception.FCSanLookupServiceException:
                    with excutils.save_and_reraise_exception():
                        LOG.error(_("Failed collecting name server info from "
                                    "fabric %s") % fabric_ip)
                except Exception as e:
                    msg = _("SSH connection failed "
                            "for %(fabric)s with error: %(err)s"
                            ) % {'fabric': fabric_ip, 'err': e}
                    LOG.error(msg)
                    raise exception.FCSanLookupServiceException(message=msg)
                finally:
                    self.client.close()
                LOG.debug("Lookup service:nsinfo-%s", nsinfo)
                LOG.debug("Lookup service:initiator list from "
                          "caller-%s", formatted_initiator_list)
                LOG.debug("Lookup service:target list from "
                          "caller-%s", formatted_target_list)
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
                    LOG.debug("No targets are in the nameserver for SAN %s",
                              fabric_name)

                if visible_initiators:
                    # getting rid of the : before returning ~sk
                    for idx, elem in enumerate(visible_initiators):
                        elem = str(elem).replace(':', '')
                        visible_initiators[idx] = elem
                else:
                    LOG.debug("No initiators are in the nameserver "
                              "for SAN %s", fabric_name)

                fabric_map = {
                    'initiator_port_wwn_list': visible_initiators,
                    'target_port_wwn_list': visible_targets
                }
                device_map[fabric_name] = fabric_map
        LOG.debug("Device map for SAN context: %s", device_map)
        return device_map

    def get_nameserver_info(self):
        """Get name server data from fabric.

        This method will return the connected node port wwn list(local
        and remote) for the given switch fabric
        """
        cli_output = None
        nsinfo_list = []
        try:
            cli_output = self._get_switch_data(ZoneConstant.NS_SHOW)
        except exception.FCSanLookupServiceException:
            with excutils.save_and_reraise_exception():
                LOG.error(_("Failed collecting nsshow info for fabric"))
        if cli_output:
            nsinfo_list = self._parse_ns_output(cli_output)
        try:
            cli_output = self._get_switch_data(ZoneConstant.NS_CAM_SHOW)
        except exception.FCSanLookupServiceException:
            with excutils.save_and_reraise_exception():
                LOG.error(_("Failed collecting nscamshow"))
        if cli_output:
            nsinfo_list.extend(self._parse_ns_output(cli_output))
        LOG.debug("Connector returning nsinfo-%s", nsinfo_list)
        return nsinfo_list

    def _get_switch_data(self, cmd):
        stdin, stdout, stderr = None, None, None
        utils.check_ssh_injection([cmd])
        try:
            stdin, stdout, stderr = self.client.exec_command(cmd)
            switch_data = stdout.readlines()
        except paramiko.SSHException as e:
            msg = (_("SSH Command failed with error '%(err)s' "
                     "'%(command)s'") % {'err': e,
                                         'command': cmd})
            LOG.error(msg)
            raise exception.FCSanLookupServiceException(message=msg)
        finally:
            if (stdin):
                stdin.flush()
                stdin.close()
            if (stdout):
                stdout.close()
            if (stderr):
                stderr.close()
        return switch_data

    def _parse_ns_output(self, switch_data):
        """Parses name server data.

        Parses nameserver raw data and adds the device port wwns to the list

        :returns list of device port wwn from ns info
        """
        nsinfo_list = []
        for line in switch_data:
            if not(" NL " in line or " N " in line):
                continue
            linesplit = line.split(';')
            if len(linesplit) > 2:
                node_port_wwn = linesplit[2]
                nsinfo_list.append(node_port_wwn)
            else:
                msg = _("Malformed nameserver string: %s") % line
                LOG.error(msg)
                raise exception.InvalidParameterValue(err=msg)
        return nsinfo_list

    def get_formatted_wwn(self, wwn_str):
        """Utility API that formats WWN to insert ':'."""
        if (len(wwn_str) != 16):
            return wwn_str.lower()
        else:
            return (':'.join([wwn_str[i:i + 2]
                              for i in range(0, len(wwn_str), 2)])).lower()
