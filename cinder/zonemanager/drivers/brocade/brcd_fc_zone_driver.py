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
Brocade Zone Driver is responsible to manage access control using FC zoning
for Brocade FC fabrics.
This is a concrete implementation of FCZoneDriver interface implementing
add_connection and delete_connection interfaces.

**Related Flags**

:zone_activate: Used by: class: 'FCZoneDriver'. Defaults to True
:zone_name_prefix: Used by: class: 'FCZoneDriver'. Defaults to 'openstack'
"""


from oslo.config import cfg

from cinder import exception
from cinder.openstack.common import excutils
from cinder.openstack.common import importutils
from cinder.openstack.common import lockutils
from cinder.openstack.common import log as logging
from cinder.zonemanager.drivers.brocade import brcd_fabric_opts as fabric_opts
from cinder.zonemanager.drivers.fc_zone_driver import FCZoneDriver

LOG = logging.getLogger(__name__)

brcd_opts = [
    cfg.StrOpt('brcd_sb_connector',
               default='cinder.zonemanager.drivers.brocade'
               '.brcd_fc_zone_client_cli.BrcdFCZoneClientCLI',
               help='Southbound connector for zoning operation'),
]

CONF = cfg.CONF
CONF.register_opts(brcd_opts, 'fc-zone-manager')


class BrcdFCZoneDriver(FCZoneDriver):
    """Brocade FC zone driver implementation.

    OpenStack Fibre Channel zone driver to manage FC zoning in
    Brocade SAN fabrics.

    Version history:
        1.0 - Initial Brocade FC zone driver
    """

    VERSION = "1.0"

    def __init__(self, **kwargs):
        super(BrcdFCZoneDriver, self).__init__(**kwargs)
        self.configuration = kwargs.get('configuration', None)
        if self.configuration:
            self.configuration.append_config_values(brcd_opts)
            # Adding a hack to hendle parameters from super classes
            # in case configured with multi backend.
            fabric_names = self.configuration.safe_get('fc_fabric_names')
            activate = self.configuration.safe_get('zone_activate')
            prefix = self.configuration.safe_get('zone_name_prefix')
            base_san_opts = []
            if not fabric_names:
                base_san_opts.append(
                    cfg.StrOpt('fc_fabric_names', default=None,
                               help='Comma separated list of fibre channel '
                               'fabric names. This list of names is used to'
                               ' retrieve other SAN credentials for connecting'
                               ' to each SAN fabric'
                               ))
            if not activate:
                base_san_opts.append(
                    cfg.BoolOpt('zone_activate',
                                default=True,
                                help='Indicates whether zone should '
                                'be activated or not'))
            if not prefix:
                base_san_opts.append(
                    cfg.StrOpt('zone_name_prefix',
                               default="openstack",
                               help="A prefix to be used when naming zone"))
            if len(base_san_opts) > 0:
                CONF.register_opts(base_san_opts)
                self.configuration.append_config_values(base_san_opts)
            fabric_names = self.configuration.fc_fabric_names.split(',')

            # There can be more than one SAN in the network and we need to
            # get credentials for each SAN.
            if fabric_names:
                self.fabric_configs = fabric_opts.load_fabric_configurations(
                    fabric_names)

    def get_formatted_wwn(self, wwn_str):
        """Utility API that formats WWN to insert ':'."""
        wwn_str = wwn_str.encode('ascii')
        if len(wwn_str) != 16:
            return wwn_str
        else:
            return ':'.join(
                [wwn_str[i:i + 2] for i in range(0, len(wwn_str), 2)])

    @lockutils.synchronized('brcd', 'fcfabric-', True)
    def add_connection(self, fabric, initiator_target_map):
        """Concrete implementation of add_connection.

        Based on zoning policy and state of each I-T pair, list of zone
        members are created and pushed to the fabric to add zones. The
        new zones created or zones updated are activated based on isActivate
        flag set in cinder.conf returned by volume driver after attach
        operation.

        :param fabric: Fabric name from cinder.conf file
        :param initiator_target_map: Mapping of initiator to list of targets
        """
        LOG.debug(_("Add connection for Fabric:%s"), fabric)
        LOG.info(_("BrcdFCZoneDriver - Add connection "
                   "for I-T map: %s"), initiator_target_map)
        fabric_ip = self.fabric_configs[fabric].safe_get('fc_fabric_address')
        fabric_user = self.fabric_configs[fabric].safe_get('fc_fabric_user')
        fabric_pwd = self.fabric_configs[fabric].safe_get('fc_fabric_password')
        fabric_port = self.fabric_configs[fabric].safe_get('fc_fabric_port')
        zoning_policy = self.configuration.zoning_policy
        zoning_policy_fab = self.fabric_configs[fabric].safe_get(
            'zoning_policy')
        if zoning_policy_fab:
            zoning_policy = zoning_policy_fab

        LOG.info(_("Zoning policy for Fabric %s"), zoning_policy)
        cli_client = None
        try:
            cli_client = importutils.import_object(
                self.configuration.brcd_sb_connector,
                ipaddress=fabric_ip,
                username=fabric_user,
                password=fabric_pwd,
                port=fabric_port)
            if not cli_client.is_supported_firmware():
                msg = _("Unsupported firmware on switch %s. Make sure "
                        "switch is running firmware v6.4 or higher"
                        ) % fabric_ip
                LOG.error(msg)
                raise exception.FCZoneDriverException(msg)
        except exception.BrocadeZoningCliException as brocade_ex:
            raise exception.FCZoneDriverException(brocade_ex)
        except Exception as e:
            LOG.error(e)
            msg = _("Failed to add zoning configuration %s") % e
            raise exception.FCZoneDriverException(msg)

        cfgmap_from_fabric = self.get_active_zone_set(
            fabric_ip, fabric_user, fabric_pwd, fabric_port)
        zone_names = []
        if cfgmap_from_fabric.get('zones'):
            zone_names = cfgmap_from_fabric['zones'].keys()
        # based on zoning policy, create zone member list and
        # push changes to fabric.
        for initiator_key in initiator_target_map.keys():
            zone_map = {}
            initiator = initiator_key.lower()
            t_list = initiator_target_map[initiator_key]
            if zoning_policy == 'initiator-target':
                for t in t_list:
                    target = t.lower()
                    zone_members = [self.get_formatted_wwn(initiator),
                                    self.get_formatted_wwn(target)]
                    zone_name = (self.configuration.zone_name_prefix
                                 + initiator.replace(':', '')
                                 + target.replace(':', ''))
                    if (
                        len(cfgmap_from_fabric) == 0 or (
                            zone_name not in zone_names)):
                        zone_map[zone_name] = zone_members
                    else:
                        # This is I-T zoning, skip if zone already exists.
                        LOG.info(_("Zone exists in I-T mode. "
                                   "Skipping zone creation %s"), zone_name)
            elif zoning_policy == 'initiator':
                zone_members = [self.get_formatted_wwn(initiator)]
                for t in t_list:
                    target = t.lower()
                    zone_members.append(self.get_formatted_wwn(target))

                zone_name = self.configuration.zone_name_prefix \
                    + initiator.replace(':', '')

                if len(zone_names) > 0 and (zone_name in zone_names):
                    zone_members = zone_members + filter(
                        lambda x: x not in zone_members,
                        cfgmap_from_fabric['zones'][zone_name])

                zone_map[zone_name] = zone_members
            else:
                msg = _("Zoning Policy: %s, not "
                        "recognized") % zoning_policy
                LOG.error(msg)
                raise exception.FCZoneDriverException(msg)

            LOG.info(_("Zone map to add: %s"), zone_map)

            if len(zone_map) > 0:
                try:
                    cli_client.add_zones(
                        zone_map, self.configuration.zone_activate)
                    cli_client.cleanup()
                except exception.BrocadeZoningCliException as brocade_ex:
                    raise exception.FCZoneDriverException(brocade_ex)
                except Exception as e:
                    LOG.error(e)
                    msg = _("Failed to add zoning configuration %s") % e
                    raise exception.FCZoneDriverException(msg)
            LOG.debug(_("Zones added successfully: %s"), zone_map)

    @lockutils.synchronized('brcd', 'fcfabric-', True)
    def delete_connection(self, fabric, initiator_target_map):
        """Concrete implementation of delete_connection.

        Based on zoning policy and state of each I-T pair, list of zones
        are created for deletion. The zones are either updated deleted based
        on the policy and attach/detach state of each I-T pair.

        :param fabric: Fabric name from cinder.conf file
        :param initiator_target_map: Mapping of initiator to list of targets
        """
        LOG.debug(_("Delete connection for fabric:%s"), fabric)
        LOG.info(_("BrcdFCZoneDriver - Delete connection for I-T map: %s"),
                 initiator_target_map)
        fabric_ip = self.fabric_configs[fabric].safe_get('fc_fabric_address')
        fabric_user = self.fabric_configs[fabric].safe_get('fc_fabric_user')
        fabric_pwd = self.fabric_configs[fabric].safe_get('fc_fabric_password')
        fabric_port = self.fabric_configs[fabric].safe_get('fc_fabric_port')
        zoning_policy = self.configuration.zoning_policy
        zoning_policy_fab = self.fabric_configs[fabric].safe_get(
            'zoning_policy')
        if zoning_policy_fab:
            zoning_policy = zoning_policy_fab

        LOG.info(_("Zoning policy for fabric %s"), zoning_policy)
        conn = None
        try:
            conn = importutils.import_object(
                self.configuration.brcd_sb_connector,
                ipaddress=fabric_ip,
                username=fabric_user,
                password=fabric_pwd,
                port=fabric_port)
            if not conn.is_supported_firmware():
                msg = _("Unsupported firmware on switch %s. Make sure "
                        "switch is running firmware v6.4 or higher"
                        ) % fabric_ip
                LOG.error(msg)
                raise exception.FCZoneDriverException(msg)
        except exception.BrocadeZoningCliException as brocade_ex:
            raise exception.FCZoneDriverException(brocade_ex)
        except Exception as e:
            LOG.error(e)
            msg = _("Failed to delete zoning configuration %s") % e
            raise exception.FCZoneDriverException(msg)

        cfgmap_from_fabric = self.get_active_zone_set(
            fabric_ip, fabric_user, fabric_pwd, fabric_port)
        zone_names = []
        if cfgmap_from_fabric.get('zones'):
            zone_names = cfgmap_from_fabric['zones'].keys()

        # Based on zoning policy, get zone member list and push changes to
        # fabric. This operation could result in an update for zone config
        # with new member list or deleting zones from active cfg.
        LOG.debug(_("zone config from Fabric: %s"), cfgmap_from_fabric)
        for initiator_key in initiator_target_map.keys():
            initiator = initiator_key.lower()
            formatted_initiator = self.get_formatted_wwn(initiator)
            zone_map = {}
            zones_to_delete = []
            t_list = initiator_target_map[initiator_key]
            if zoning_policy == 'initiator-target':
                # In this case, zone needs to be deleted.
                for t in t_list:
                    target = t.lower()
                    zone_name = (
                        self.configuration.zone_name_prefix
                        + initiator.replace(':', '')
                        + target.replace(':', ''))
                    LOG.debug(_("Zone name to del: %s"), zone_name)
                    if len(zone_names) > 0 and (zone_name in zone_names):
                        # delete zone.
                        LOG.debug(("Added zone to delete to "
                                   "list: %s"), zone_name)
                        zones_to_delete.append(zone_name)

            elif zoning_policy == 'initiator':
                zone_members = [formatted_initiator]
                for t in t_list:
                    target = t.lower()
                    zone_members.append(self.get_formatted_wwn(target))

                zone_name = self.configuration.zone_name_prefix \
                    + initiator.replace(':', '')

                if (zone_names and (zone_name in zone_names)):
                    filtered_members = filter(
                        lambda x: x not in zone_members,
                        cfgmap_from_fabric['zones'][zone_name])

                    # The assumption here is that initiator is always there
                    # in the zone as it is 'initiator' policy. We find the
                    # filtered list and if it is non-empty, add initiator
                    # to it and update zone if filtered list is empty, we
                    # remove that zone.
                    LOG.debug(_("Zone delete - I mode: "
                                "filtered targets:%s"), filtered_members)
                    if filtered_members:
                        filtered_members.append(formatted_initiator)
                        LOG.debug(_("Filtered zone members to "
                                    "update: %s"), filtered_members)
                        zone_map[zone_name] = filtered_members
                        LOG.debug(_("Filtered zone Map to "
                                    "update: %s"), zone_map)
                    else:
                        zones_to_delete.append(zone_name)
            else:
                LOG.info(_("Zoning Policy: %s, not "
                           "recognized"), zoning_policy)
            LOG.debug(_("Final Zone map to update: %s"), zone_map)
            LOG.debug(_("Final Zone list to delete: %s"), zones_to_delete)
            try:
                # Update zone membership.
                if zone_map:
                    conn.add_zones(
                        zone_map, self.configuration.zone_activate)
                # Delete zones ~sk.
                if zones_to_delete:
                    zone_name_string = ''
                    num_zones = len(zones_to_delete)
                    for i in range(0, num_zones):
                        if i == 0:
                            zone_name_string = (
                                '%s%s' % (
                                    zone_name_string, zones_to_delete[i]))
                        else:
                            zone_name_string = '%s%s%s' % (
                                zone_name_string, ';', zones_to_delete[i])

                    conn.delete_zones(
                        zone_name_string, self.configuration.zone_activate)
                conn.cleanup()
            except Exception as e:
                LOG.error(e)
                msg = _("Failed to update or delete zoning configuration")
                raise exception.FCZoneDriverException(msg)

    def get_san_context(self, target_wwn_list):
        """Lookup SAN context for visible end devices.

        Look up each SAN configured and return a map of SAN (fabric IP) to
        list of target WWNs visible to the fabric.
        """
        # TODO(Santhosh Kolathur): consider refactoring to use lookup service.
        formatted_target_list = []
        fabric_map = {}
        fabrics = self.configuration.fc_fabric_names.split(',')
        LOG.debug(_("Fabric List: %s"), fabrics)
        LOG.debug(_("Target wwn List: %s"), target_wwn_list)
        if len(fabrics) > 0:
            for t in target_wwn_list:
                formatted_target_list.append(self.get_formatted_wwn(t.lower()))
            LOG.debug(_("Formatted Target wwn List:"
                        " %s"), formatted_target_list)
            for fabric_name in fabrics:
                fabric_ip = self.fabric_configs[fabric_name].safe_get(
                    'fc_fabric_address')
                fabric_user = self.fabric_configs[fabric_name].safe_get(
                    'fc_fabric_user')
                fabric_pwd = self.fabric_configs[fabric_name].safe_get(
                    'fc_fabric_password')
                fabric_port = self.fabric_configs[fabric_name].safe_get(
                    'fc_fabric_port')
                conn = None
                try:
                    conn = importutils.import_object(
                        self.configuration.brcd_sb_connector,
                        ipaddress=fabric_ip,
                        username=fabric_user,
                        password=fabric_pwd,
                        port=fabric_port)
                    if not conn.is_supported_firmware():
                        msg = _("Unsupported firmware on switch %s. Make sure "
                                "switch is running firmware v6.4 or higher"
                                ) % fabric_ip
                        LOG.error(msg)
                        raise exception.FCZoneDriverException(msg)
                except exception.BrocadeZoningCliException as brocade_ex:
                    raise exception.FCZoneDriverException(brocade_ex)
                except Exception as e:
                    LOG.error(e)
                    msg = _("Failed to get SAN context %s") % e
                    raise exception.FCZoneDriverException(msg)

                # Get name server data from fabric and get the targets
                # logged in.
                nsinfo = None
                try:
                    nsinfo = conn.get_nameserver_info()
                    LOG.debug(_("name server info from fabric:%s"), nsinfo)
                    conn.cleanup()
                except exception.BrocadeZoningCliException as ex:
                    with excutils.save_and_reraise_exception():
                        LOG.error(_("Error getting name server "
                                    "info: %s"), ex)
                except Exception as e:
                    msg = (_("Failed to get name server info:%s") % e)
                    LOG.error(msg)
                    raise exception.FCZoneDriverException(msg)
                visible_targets = filter(
                    lambda x: x in formatted_target_list,
                    nsinfo)

                if visible_targets:
                    LOG.info(_("Filtered targets for SAN is: %s"),
                             {fabric_name: visible_targets})
                    # getting rid of the ':' before returning
                    for idx, elem in enumerate(visible_targets):
                        visible_targets[idx] = str(
                            visible_targets[idx]).replace(':', '')
                    fabric_map[fabric_name] = visible_targets
                else:
                    LOG.debug(_("No targets are in the nameserver for SAN %s"),
                              fabric_name)
        LOG.debug(_("Return SAN context output:%s"), fabric_map)
        return fabric_map

    def get_active_zone_set(self, fabric_ip,
                            fabric_user, fabric_pwd, fabric_port):
        """Gets active zone config from fabric."""
        cfgmap = {}
        conn = None
        try:
            LOG.debug(_("Southbound connector:"
                        " %s"), self.configuration.brcd_sb_connector)
            conn = importutils.import_object(
                self.configuration.brcd_sb_connector,
                ipaddress=fabric_ip, username=fabric_user,
                password=fabric_pwd, port=fabric_port)
            if not conn.is_supported_firmware():
                msg = _("Unsupported firmware on switch %s. Make sure "
                        "switch is running firmware v6.4 or higher"
                        ) % fabric_ip
                LOG.error(msg)
                raise exception.FCZoneDriverException(msg)
            cfgmap = conn.get_active_zone_set()
            conn.cleanup()
        except exception.BrocadeZoningCliException as brocade_ex:
            raise exception.FCZoneDriverException(brocade_ex)
        except Exception as e:
            msg = (_("Failed to access active zoning configuration:%s") % e)
            LOG.error(msg)
            raise exception.FCZoneDriverException(msg)
        LOG.debug(_("Active zone set from fabric: %s"), cfgmap)
        return cfgmap
