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
Cisco Zone Driver is responsible to manage access control using FC zoning
for Cisco FC fabrics.
This is a concrete implementation of FCZoneDriver interface implementing
add_connection and delete_connection interfaces.

**Related Flags**

:zone_activate: Used by: class: 'FCZoneDriver'. Defaults to True
:zone_name_prefix: Used by: class: 'FCZoneDriver'. Defaults to 'openstack'
"""

from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import importutils
import six
import string

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.zonemanager.drivers.cisco import cisco_fabric_opts as fabric_opts
from cinder.zonemanager.drivers.cisco import fc_zone_constants as ZoneConstant
from cinder.zonemanager.drivers import driver_utils
from cinder.zonemanager.drivers import fc_zone_driver
from cinder.zonemanager import utils as zm_utils

LOG = logging.getLogger(__name__)

SUPPORTED_CHARS = string.ascii_letters + string.digits + '$' + '-' + '^' + '_'
cisco_opts = [
    cfg.StrOpt('cisco_sb_connector',
               default='cinder.zonemanager.drivers.cisco'
               '.cisco_fc_zone_client_cli.CiscoFCZoneClientCLI',
               help='Southbound connector for zoning operation'),
]

CONF = cfg.CONF
CONF.register_opts(cisco_opts, group='fc-zone-manager')


@interface.fczmdriver
class CiscoFCZoneDriver(fc_zone_driver.FCZoneDriver):
    """Cisco FC zone driver implementation.

    OpenStack Fibre Channel zone driver to manage FC zoning in
    Cisco SAN fabrics.

    Version history:
        1.0 - Initial Cisco FC zone driver
        1.1 - Added friendly zone name support
    """

    VERSION = "1.1.0"

    # ThirdPartySystems wiki name
    CI_WIKI_NAME = "Cisco_ZM_CI"

    def __init__(self, **kwargs):
        super(CiscoFCZoneDriver, self).__init__(**kwargs)
        self.configuration = kwargs.get('configuration', None)
        if self.configuration:
            self.configuration.append_config_values(cisco_opts)

            # Adding a hack to handle parameters from super classes
            # in case configured with multi backends.
            fabric_names = self.configuration.safe_get('fc_fabric_names')
            activate = self.configuration.safe_get('cisco_zone_activate')
            prefix = self.configuration.safe_get('cisco_zone_name_prefix')
            base_san_opts = []
            if not fabric_names:
                base_san_opts.append(
                    cfg.StrOpt('fc_fabric_names',
                               help='Comma separated list of fibre channel '
                               'fabric names. This list of names is used to'
                               ' retrieve other SAN credentials for connecting'
                               ' to each SAN fabric'
                               ))
            if not activate:
                base_san_opts.append(
                    cfg.BoolOpt('cisco_zone_activate',
                                default=True,
                                help='Indicates whether zone should '
                                'be activated or not'))
            if not prefix:
                base_san_opts.append(
                    cfg.StrOpt('cisco_zone_name_prefix',
                               default="openstack",
                               help="A prefix to be used when naming zone"))
            if len(base_san_opts) > 0:
                CONF.register_opts(base_san_opts)
                self.configuration.append_config_values(base_san_opts)
            fabric_names = [x.strip() for x in self.
                            configuration.fc_fabric_names.split(',')]

            # There can be more than one SAN in the network and we need to
            # get credentials for each SAN.
            if fabric_names:
                self.fabric_configs = fabric_opts.load_fabric_configurations(
                    fabric_names)

    @lockutils.synchronized('cisco', 'fcfabric-', True)
    def add_connection(self, fabric, initiator_target_map, host_name=None,
                       storage_system=None):
        """Concrete implementation of add_connection.

        Based on zoning policy and state of each I-T pair, list of zone
        members are created and pushed to the fabric to add zones. The
        new zones created or zones updated are activated based on isActivate
        flag set in cinder.conf returned by volume driver after attach
        operation.

        :param fabric: Fabric name from cinder.conf file
        :param initiator_target_map: Mapping of initiator to list of targets
        """

        LOG.debug("Add connection for Fabric: %s", fabric)
        LOG.info("CiscoFCZoneDriver - Add connection "
                 "for I-T map: %s", initiator_target_map)
        fabric_ip = self.fabric_configs[fabric].safe_get(
            'cisco_fc_fabric_address')
        fabric_user = self.fabric_configs[fabric].safe_get(
            'cisco_fc_fabric_user')
        fabric_pwd = self.fabric_configs[fabric].safe_get(
            'cisco_fc_fabric_password')
        fabric_port = self.fabric_configs[fabric].safe_get(
            'cisco_fc_fabric_port')
        zoning_policy = self.configuration.zoning_policy
        zoning_policy_fab = self.fabric_configs[fabric].safe_get(
            'cisco_zoning_policy')
        if zoning_policy_fab:
            zoning_policy = zoning_policy_fab

        zoning_vsan = self.fabric_configs[fabric].safe_get('cisco_zoning_vsan')

        LOG.info("Zoning policy for Fabric %s", zoning_policy)

        statusmap_from_fabric = self.get_zoning_status(
            fabric_ip, fabric_user, fabric_pwd, fabric_port, zoning_vsan)

        if statusmap_from_fabric.get('session') == 'none':

            cfgmap_from_fabric = self.get_active_zone_set(
                fabric_ip, fabric_user, fabric_pwd, fabric_port, zoning_vsan)
            zone_names = []
            if cfgmap_from_fabric.get('zones'):
                zone_names = cfgmap_from_fabric['zones'].keys()
            # based on zoning policy, create zone member list and
            # push changes to fabric.
            for initiator_key in initiator_target_map.keys():
                zone_map = {}
                zone_update_map = {}
                initiator = initiator_key.lower()
                t_list = initiator_target_map[initiator_key]
                if zoning_policy == 'initiator-target':
                    for t in t_list:
                        target = t.lower()
                        zone_members = [
                            zm_utils.get_formatted_wwn(initiator),
                            zm_utils.get_formatted_wwn(target)]
                        zone_name = (
                            driver_utils.get_friendly_zone_name(
                                zoning_policy,
                                initiator,
                                target,
                                host_name,
                                storage_system,
                                self.configuration.cisco_zone_name_prefix,
                                SUPPORTED_CHARS))
                        if (len(cfgmap_from_fabric) == 0 or (
                                zone_name not in zone_names)):
                            zone_map[zone_name] = zone_members
                        else:
                            # This is I-T zoning, skip if zone exists.
                            LOG.info("Zone exists in I-T mode. "
                                     "Skipping zone creation %s",
                                     zone_name)
                elif zoning_policy == 'initiator':
                    zone_members = [
                        zm_utils.get_formatted_wwn(initiator)]
                    for t in t_list:
                        target = t.lower()
                        zone_members.append(
                            zm_utils.get_formatted_wwn(target))
                    zone_name = (
                        driver_utils.get_friendly_zone_name(
                            zoning_policy,
                            initiator,
                            target,
                            host_name,
                            storage_system,
                            self.configuration.cisco_zone_name_prefix,
                            SUPPORTED_CHARS))

                    # If zone exists, then perform a update_zone and add
                    # new members into existing zone.
                    if zone_name and (zone_name in zone_names):
                        zone_members = filter(
                            lambda x: x not in
                            cfgmap_from_fabric['zones'][zone_name],
                            zone_members)
                        if zone_members:
                            zone_update_map[zone_name] = zone_members
                    else:
                        zone_map[zone_name] = zone_members
                else:
                    msg = _("Zoning Policy: %s, not"
                            " recognized") % zoning_policy
                    LOG.error(msg)
                    raise exception.FCZoneDriverException(msg)

            LOG.info("Zone map to add: %(zone_map)s",
                     {'zone_map': zone_map})
            LOG.info("Zone map to update add: %(zone_update_map)s",
                     {'zone_update_map': zone_update_map})
            if zone_map or zone_update_map:
                conn = None
                try:
                    conn = importutils.import_object(
                        self.configuration.cisco_sb_connector,
                        ipaddress=fabric_ip,
                        username=fabric_user,
                        password=fabric_pwd,
                        port=fabric_port,
                        vsan=zoning_vsan)
                    if zone_map:
                        conn.add_zones(
                            zone_map,
                            self.configuration.cisco_zone_activate,
                            zoning_vsan, cfgmap_from_fabric,
                            statusmap_from_fabric)
                    if zone_update_map:
                        conn.update_zones(
                            zone_update_map,
                            self.configuration.cisco_zone_activate,
                            zoning_vsan, ZoneConstant.ZONE_ADD,
                            cfgmap_from_fabric,
                            statusmap_from_fabric)
                    conn.cleanup()
                except exception.CiscoZoningCliException as cisco_ex:
                    msg = _("Exception: %s") % six.text_type(cisco_ex)
                    raise exception.FCZoneDriverException(msg)
                except Exception:
                    msg = _("Failed to add zoning configuration.")
                    LOG.exception(msg)
                    raise exception.FCZoneDriverException(msg)
                LOG.debug("Zones added successfully: %s", zone_map)
            else:
                LOG.debug("Zones already exist - Initiator Target Map: %s",
                          initiator_target_map)
        else:
            LOG.debug("Zoning session exists VSAN: %s", zoning_vsan)

    @lockutils.synchronized('cisco', 'fcfabric-', True)
    def delete_connection(self, fabric, initiator_target_map, host_name=None,
                          storage_system=None):
        """Concrete implementation of delete_connection.

        Based on zoning policy and state of each I-T pair, list of zones
        are created for deletion. The zones are either updated deleted based
        on the policy and attach/detach state of each I-T pair.

        :param fabric: Fabric name from cinder.conf file
        :param initiator_target_map: Mapping of initiator to list of targets
        """
        LOG.debug("Delete connection for fabric: %s", fabric)
        LOG.info("CiscoFCZoneDriver - Delete connection for I-T map: %s",
                 initiator_target_map)
        fabric_ip = self.fabric_configs[fabric].safe_get(
            'cisco_fc_fabric_address')
        fabric_user = self.fabric_configs[fabric].safe_get(
            'cisco_fc_fabric_user')
        fabric_pwd = self.fabric_configs[fabric].safe_get(
            'cisco_fc_fabric_password')
        fabric_port = self.fabric_configs[fabric].safe_get(
            'cisco_fc_fabric_port')
        zoning_policy = self.configuration.zoning_policy
        zoning_policy_fab = self.fabric_configs[fabric].safe_get(
            'cisco_zoning_policy')

        if zoning_policy_fab:
            zoning_policy = zoning_policy_fab

        zoning_vsan = self.fabric_configs[fabric].safe_get('cisco_zoning_vsan')

        LOG.info("Zoning policy for fabric %s", zoning_policy)

        statusmap_from_fabric = self.get_zoning_status(
            fabric_ip, fabric_user, fabric_pwd, fabric_port, zoning_vsan)

        if statusmap_from_fabric.get('session') == 'none':
            cfgmap_from_fabric = self.get_active_zone_set(
                fabric_ip, fabric_user, fabric_pwd, fabric_port, zoning_vsan)

            zone_names = []
            if cfgmap_from_fabric.get('zones'):
                zone_names = cfgmap_from_fabric['zones'].keys()

            # Based on zoning policy, get zone member list and push
            # changes to fabric. This operation could result in an update
            # for zone config with new member list or deleting zones from
            # active cfg.

            LOG.debug("zone config from Fabric: %s", cfgmap_from_fabric)
            for initiator_key in initiator_target_map.keys():
                initiator = initiator_key.lower()
                formatted_initiator = zm_utils.get_formatted_wwn(initiator)
                zone_update_map = {}
                zones_to_delete = []
                t_list = initiator_target_map[initiator_key]
                if zoning_policy == 'initiator-target':
                    # In this case, zone needs to be deleted.
                    for t in t_list:
                        target = t.lower()
                        zone_name = (
                            driver_utils.get_friendly_zone_name(
                                zoning_policy,
                                initiator,
                                target,
                                host_name,
                                storage_system,
                                self.configuration.cisco_zone_name_prefix,
                                SUPPORTED_CHARS))
                        LOG.debug("Zone name to del: %s", zone_name)
                        if (len(zone_names) > 0 and (zone_name in zone_names)):
                            # delete zone.
                            LOG.debug("Added zone to delete to list: %s",
                                      zone_name)
                            zones_to_delete.append(zone_name)

                elif zoning_policy == 'initiator':
                    zone_members = [formatted_initiator]
                    for t in t_list:
                        target = t.lower()
                        zone_members.append(
                            zm_utils.get_formatted_wwn(target))

                    zone_name = driver_utils.get_friendly_zone_name(
                        zoning_policy,
                        initiator,
                        target,
                        host_name,
                        storage_system,
                        self.configuration.cisco_zone_name_prefix,
                        SUPPORTED_CHARS)
                    # Check if there are zone members leftover after removal
                    if (zone_names and (zone_name in zone_names)):
                        filtered_members = filter(
                            lambda x: x not in zone_members,
                            cfgmap_from_fabric['zones'][zone_name])

                        # The assumption here is that initiator is always
                        # there in the zone as it is 'initiator' policy.
                        # If filtered list is empty, we remove that zone.
                        # If there are other members leftover, then perform
                        # update_zone to remove targets
                        LOG.debug("Zone delete - I mode: filtered targets: %s",
                                  filtered_members)
                        if filtered_members:
                            remove_members = filter(
                                lambda x: x in
                                cfgmap_from_fabric['zones'][zone_name],
                                zone_members)
                            if remove_members:
                                # Do not want to remove the initiator
                                remove_members.remove(formatted_initiator)
                                LOG.debug("Zone members to remove: %s",
                                          remove_members)
                                zone_update_map[zone_name] = remove_members
                                LOG.debug("Filtered zone Map to update: %s",
                                          zone_update_map)
                        else:
                            zones_to_delete.append(zone_name)
                else:
                    LOG.info("Zoning Policy: %s, not recognized",
                             zoning_policy)
                LOG.debug("Zone map to remove update: %s", zone_update_map)
                LOG.debug("Final Zone list to delete: %s", zones_to_delete)
                conn = None
                try:
                    conn = importutils.import_object(
                        self.configuration.cisco_sb_connector,
                        ipaddress=fabric_ip,
                        username=fabric_user,
                        password=fabric_pwd,
                        port=fabric_port,
                        vsan=zoning_vsan)
                    # Update zone membership.
                    if zone_update_map:
                        conn.update_zones(
                            zone_update_map,
                            self.configuration.cisco_zone_activate,
                            zoning_vsan, ZoneConstant.ZONE_REMOVE,
                            cfgmap_from_fabric, statusmap_from_fabric)
                    # Delete zones ~sk.
                    if zones_to_delete:
                        zone_name_string = ''
                        num_zones = len(zones_to_delete)
                        for i in range(0, num_zones):
                            if i == 0:
                                zone_name_string = ('%s%s' % (
                                                    zone_name_string,
                                                    zones_to_delete[i]))
                            else:
                                zone_name_string = ('%s%s%s' % (
                                                    zone_name_string, ';',
                                                    zones_to_delete[i]))

                        conn.delete_zones(zone_name_string,
                                          self.configuration.
                                          cisco_zone_activate,
                                          zoning_vsan, cfgmap_from_fabric,
                                          statusmap_from_fabric)
                    conn.cleanup()
                except Exception:
                    msg = _("Failed to update or delete zoning configuration")
                    LOG.exception(msg)
                    raise exception.FCZoneDriverException(msg)
                LOG.debug("Zones deleted successfully: %s", zone_update_map)
            else:
                LOG.debug("Zoning session exists VSAN: %s", zoning_vsan)

    def get_san_context(self, target_wwn_list):
        """Lookup SAN context for visible end devices.

        Look up each SAN configured and return a map of SAN (fabric IP) to
        list of target WWNs visible to the fabric.
        """
        formatted_target_list = []
        fabric_map = {}
        fabrics = [x.strip() for x in self.
                   configuration.fc_fabric_names.split(',')]
        LOG.debug("Fabric List: %s", fabrics)
        LOG.debug("Target wwn List: %s", target_wwn_list)
        if len(fabrics) > 0:
            for t in target_wwn_list:
                formatted_target_list.append(
                    zm_utils.get_formatted_wwn(t.lower()))
            LOG.debug("Formatted Target wwn List: %s", formatted_target_list)
            for fabric_name in fabrics:
                fabric_ip = self.fabric_configs[fabric_name].safe_get(
                    'cisco_fc_fabric_address')
                fabric_user = self.fabric_configs[fabric_name].safe_get(
                    'cisco_fc_fabric_user')
                fabric_pwd = self.fabric_configs[fabric_name].safe_get(
                    'cisco_fc_fabric_password')
                fabric_port = self.fabric_configs[fabric_name].safe_get(
                    'cisco_fc_fabric_port')
                zoning_vsan = self.fabric_configs[fabric_name].safe_get(
                    'cisco_zoning_vsan')

                # Get name server data from fabric and get the targets
                # logged in.
                nsinfo = None
                try:
                    conn = importutils.import_object(
                        self.configuration.cisco_sb_connector,
                        ipaddress=fabric_ip,
                        username=fabric_user,
                        password=fabric_pwd, port=fabric_port,
                        vsan=zoning_vsan)
                    nsinfo = conn.get_nameserver_info()
                    LOG.debug("show fcns database info from fabric: %s",
                              nsinfo)
                    conn.cleanup()
                except exception.CiscoZoningCliException:
                    with excutils.save_and_reraise_exception():
                        LOG.exception("Error getting show fcns database info.")
                except Exception:
                    msg = _("Failed to get show fcns database info.")
                    LOG.exception(msg)
                    raise exception.FCZoneDriverException(msg)
                visible_targets = filter(
                    lambda x: x in formatted_target_list, nsinfo)

                if visible_targets:
                    LOG.info("Filtered targets for SAN is: %s",
                             {fabric_name: visible_targets})
                    # getting rid of the ':' before returning
                    for idx, elem in enumerate(visible_targets):
                        visible_targets[idx] = six.text_type(
                            visible_targets[idx]).replace(':', '')
                    fabric_map[fabric_name] = visible_targets
                else:
                    LOG.debug("No targets are in the fcns info for SAN %s",
                              fabric_name)
        LOG.debug("Return SAN context output: %s", fabric_map)
        return fabric_map

    def get_active_zone_set(self, fabric_ip,
                            fabric_user, fabric_pwd, fabric_port,
                            zoning_vsan):
        """Gets active zoneset config for vsan."""
        cfgmap = {}
        conn = None
        try:
            LOG.debug("Southbound connector: %s",
                      self.configuration.cisco_sb_connector)
            conn = importutils.import_object(
                self.configuration.cisco_sb_connector,
                ipaddress=fabric_ip, username=fabric_user,
                password=fabric_pwd, port=fabric_port, vsan=zoning_vsan)
            cfgmap = conn.get_active_zone_set()
            conn.cleanup()
        except Exception:
            msg = _("Failed to access active zoning configuration.")
            LOG.exception(msg)
            raise exception.FCZoneDriverException(msg)
        LOG.debug("Active zone set from fabric: %s", cfgmap)
        return cfgmap

    def get_zoning_status(self, fabric_ip, fabric_user, fabric_pwd,
                          fabric_port, zoning_vsan):
        """Gets zoneset status and mode."""
        statusmap = {}
        conn = None
        try:
            LOG.debug("Southbound connector: %s",
                      self.configuration.cisco_sb_connector)
            conn = importutils.import_object(
                self.configuration.cisco_sb_connector,
                ipaddress=fabric_ip, username=fabric_user,
                password=fabric_pwd, port=fabric_port, vsan=zoning_vsan)
            statusmap = conn.get_zoning_status()
            conn.cleanup()
        except Exception:
            msg = _("Failed to access zoneset status:%s")
            LOG.exception(msg)
            raise exception.FCZoneDriverException(msg)
        LOG.debug("Zoneset status from fabric: %s", statusmap)
        return statusmap
