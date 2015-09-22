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

from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_utils import excutils
import six

from cinder import exception
from cinder.i18n import _, _LE
from cinder import ssh_utils
from cinder import utils
from cinder.zonemanager.drivers.brocade import brcd_fabric_opts as fabric_opts
import cinder.zonemanager.drivers.brocade.fc_zone_constants as zone_constant
from cinder.zonemanager import fc_san_lookup_service as fc_service

LOG = logging.getLogger(__name__)


class BrcdFCSanLookupService(fc_service.FCSanLookupService):
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

                ssh_pool = ssh_utils.SSHPool(fabric_ip, fabric_port, None,
                                             fabric_user, password=fabric_pwd)

                # Get name server data from fabric and find the targets
                # logged in
                nsinfo = ''
                try:
                    LOG.debug("Getting name server data for "
                              "fabric %s", fabric_ip)
                    nsinfo = self.get_nameserver_info(ssh_pool)
                except exception.FCSanLookupServiceException:
                    with excutils.save_and_reraise_exception():
                        LOG.error(_LE("Failed collecting name server info from"
                                      " fabric %s"), fabric_ip)
                except Exception as e:
                    msg = _("SSH connection failed "
                            "for %(fabric)s with error: %(err)s"
                            ) % {'fabric': fabric_ip, 'err': e}
                    LOG.error(msg)
                    raise exception.FCSanLookupServiceException(message=msg)

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

    def get_nameserver_info(self, ssh_pool):
        """Get name server data from fabric.

        This method will return the connected node port wwn list(local
        and remote) for the given switch fabric

        :param ssh_pool: SSH connections for the current fabric
        """
        cli_output = None
        nsinfo_list = []
        try:
            cli_output = self._get_switch_data(ssh_pool,
                                               zone_constant.NS_SHOW)
        except exception.FCSanLookupServiceException:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Failed collecting nsshow info for fabric"))
        if cli_output:
            nsinfo_list = self._parse_ns_output(cli_output)
        try:
            cli_output = self._get_switch_data(ssh_pool,
                                               zone_constant.NS_CAM_SHOW)

        except exception.FCSanLookupServiceException:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Failed collecting nscamshow"))
        if cli_output:
            nsinfo_list.extend(self._parse_ns_output(cli_output))
        LOG.debug("Connector returning nsinfo-%s", nsinfo_list)
        return nsinfo_list

    def _get_switch_data(self, ssh_pool, cmd):
        utils.check_ssh_injection([cmd])

        with ssh_pool.item() as ssh:
            try:
                switch_data, err = processutils.ssh_execute(ssh, cmd)
            except processutils.ProcessExecutionError as e:
                msg = (_("SSH Command failed with error: '%(err)s', Command: "
                         "'%(command)s'") % {'err': six.text_type(e),
                                             'command': cmd})
                LOG.error(msg)
                raise exception.FCSanLookupServiceException(message=msg)

        return switch_data

    def _parse_ns_output(self, switch_data):
        """Parses name server data.

        Parses nameserver raw data and adds the device port wwns to the list

        :returns list of device port wwn from ns info
        """
        nsinfo_list = []
        lines = switch_data.split('\n')
        for line in lines:
            if not(" NL " in line or " N " in line):
                continue
            linesplit = line.split(';')
            if len(linesplit) > 2:
                node_port_wwn = linesplit[2].strip()
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
