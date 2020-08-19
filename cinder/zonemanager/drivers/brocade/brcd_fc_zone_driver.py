#    (c) Copyright 2019 Brocade, a Broadcom Company
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
Brocade Zone Driver is responsible to manage access control using FC zoning
for Brocade FC fabrics.
This is a concrete implementation of FCZoneDriver interface implementing
add_connection and delete_connection interfaces.

**Related Flags**

:zone_activate: Used by: class: 'FCZoneDriver'. Defaults to True
:zone_name_prefix: Used by: class: 'FCZoneDriver'. Defaults to 'openstack'
"""

import string

from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import importutils
import six

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.zonemanager.drivers.brocade import brcd_fabric_opts as fabric_opts
from cinder.zonemanager.drivers.brocade import exception as b_exception
from cinder.zonemanager.drivers.brocade import fc_zone_constants
from cinder.zonemanager.drivers import driver_utils
from cinder.zonemanager.drivers import fc_zone_driver
from cinder.zonemanager import utils

LOG = logging.getLogger(__name__)

SUPPORTED_CHARS = string.ascii_letters + string.digits + '_'
brcd_opts = [
    cfg.StrOpt('brcd_sb_connector',
               default=fc_zone_constants.HTTP.upper(),
               help='South bound connector for zoning operation'),
]

CONF = cfg.CONF
CONF.register_opts(brcd_opts, group='fc-zone-manager')


@interface.fczmdriver
class BrcdFCZoneDriver(fc_zone_driver.FCZoneDriver):
    """Brocade FC zone driver implementation.

    OpenStack Fibre Channel zone driver to manage FC zoning in
    Brocade SAN fabrics.

    .. code-block:: none

      Version history:
        1.0 - Initial Brocade FC zone driver
        1.1 - Implements performance enhancements
        1.2 - Added support for friendly zone name
        1.3 - Added HTTP connector support
        1.4 - Adds support to zone in Virtual Fabrics
        1.5 - Initiator zoning updates through zoneadd/zoneremove
        1.6 - Add REST connector
    """

    VERSION = "1.6"

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "Brocade_OpenStack_CI"

    # TODO(smcginnis) Evaluate removing plans once we get to the V release
    SUPPORTED = False

    def __init__(self, **kwargs):
        super(BrcdFCZoneDriver, self).__init__(**kwargs)
        self.sb_conn_map = {}
        self.configuration = kwargs.get('configuration', None)
        if self.configuration:
            self.configuration.append_config_values(brcd_opts)
            # Adding a hack to handle parameters from super classes
            # in case configured with multiple back ends.
            fabric_names = self.configuration.safe_get('fc_fabric_names')
            base_san_opts = []
            if not fabric_names:
                base_san_opts.append(
                    cfg.StrOpt('fc_fabric_names',
                               help='Comma separated list of fibre channel '
                               'fabric names. This list of names is used to'
                               ' retrieve other SAN credentials for connecting'
                               ' to each SAN fabric'
                               ))
            if len(base_san_opts) > 0:
                CONF.register_opts(base_san_opts)
                self.configuration.append_config_values(base_san_opts)

            fc_fabric_names = self.configuration.fc_fabric_names
            fabric_names = [x.strip() for x in fc_fabric_names.split(',')]

            # There can be more than one SAN in the network and we need to
            # get credentials for each SAN.
            if fabric_names:
                self.fabric_configs = fabric_opts.load_fabric_configurations(
                    fabric_names)

    @staticmethod
    def get_driver_options():
        return fabric_opts.brcd_zone_opts + brcd_opts

    @lockutils.synchronized('brcd', 'fcfabric-', True)
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
        LOG.info("BrcdFCZoneDriver - Add connection for fabric "
                 "%(fabric)s for I-T map: %(i_t_map)s",
                 {'fabric': fabric,
                  'i_t_map': initiator_target_map})
        zoning_policy = self.configuration.zoning_policy
        zoning_policy_fab = self.fabric_configs[fabric].safe_get(
            'zoning_policy')
        zone_name_prefix = self.fabric_configs[fabric].safe_get(
            'zone_name_prefix')
        zone_activate = self.fabric_configs[fabric].safe_get(
            'zone_activate')
        if zoning_policy_fab:
            zoning_policy = zoning_policy_fab
        LOG.info("Zoning policy for Fabric %(policy)s",
                 {'policy': zoning_policy})
        if (zoning_policy != 'initiator'
                and zoning_policy != 'initiator-target'):
            LOG.info("Zoning policy is not valid, "
                     "no zoning will be performed.")
            return

        client = self._get_southbound_client(fabric)
        cfgmap_from_fabric = self._get_active_zone_set(client)

        zone_names = []
        if cfgmap_from_fabric.get('zones'):
            zone_names = cfgmap_from_fabric['zones'].keys()
        # based on zoning policy, create zone member list and
        # push changes to fabric.
        for initiator_key in initiator_target_map.keys():
            zone_map = {}
            zone_update_map = {}
            initiator = initiator_key.lower()
            target_list = initiator_target_map[initiator_key]
            if zoning_policy == 'initiator-target':
                for target in target_list:
                    zone_members = [utils.get_formatted_wwn(initiator),
                                    utils.get_formatted_wwn(target)]
                    zone_name = driver_utils.get_friendly_zone_name(
                        zoning_policy,
                        initiator,
                        target,
                        host_name,
                        storage_system,
                        zone_name_prefix,
                        SUPPORTED_CHARS)
                    if (len(cfgmap_from_fabric) == 0 or (
                            zone_name not in zone_names)):
                        zone_map[zone_name] = zone_members
                    else:
                        # This is I-T zoning, skip if zone already exists.
                        LOG.info("Zone exists in I-T mode. Skipping "
                                 "zone creation for %(zonename)s",
                                 {'zonename': zone_name})
            elif zoning_policy == 'initiator':
                zone_members = [utils.get_formatted_wwn(initiator)]
                for target in target_list:
                    zone_members.append(utils.get_formatted_wwn(target))

                zone_name = driver_utils.get_friendly_zone_name(
                    zoning_policy,
                    initiator,
                    target,
                    host_name,
                    storage_system,
                    zone_name_prefix,
                    SUPPORTED_CHARS)

                # If zone exists, then do a zoneadd to update
                # the zone members in the existing zone.  Otherwise,
                # do a zonecreate to create a new zone.
                if len(zone_names) > 0 and (zone_name in zone_names):
                    # Verify that the target WWNs are not already members
                    # of the existing zone.  If so, remove them from the
                    # list of members to add, otherwise error will be
                    # returned from the switch.
                    for t in target_list:
                        if t in cfgmap_from_fabric['zones'][zone_name]:
                            zone_members.remove(utils.get_formatted_wwn(t))
                    if zone_members:
                        zone_update_map[zone_name] = zone_members
                else:
                    zone_map[zone_name] = zone_members

            LOG.info("Zone map to create: %(zonemap)s",
                     {'zonemap': zone_map})
            LOG.info("Zone map to update: %(zone_update_map)s",
                     {'zone_update_map': zone_update_map})

            try:
                if zone_map:
                    client.add_zones(zone_map, zone_activate,
                                     cfgmap_from_fabric)
                    LOG.debug("Zones created successfully: %(zonemap)s",
                              {'zonemap': zone_map})
                if zone_update_map:
                    client.update_zones(zone_update_map, zone_activate,
                                        fc_zone_constants.ZONE_ADD,
                                        cfgmap_from_fabric)
                    LOG.debug("Zones updated successfully: %(updatemap)s",
                              {'updatemap': zone_update_map})
            except (b_exception.BrocadeZoningCliException,
                    b_exception.BrocadeZoningHttpException,
                    b_exception.BrocadeZoningRestException) as brocade_ex:
                raise exception.FCZoneDriverException(brocade_ex)
            except Exception:
                msg = _("Failed to add or update zoning configuration.")
                LOG.exception(msg)
                raise exception.FCZoneDriverException(msg)
            finally:
                client.cleanup()

    @lockutils.synchronized('brcd', 'fcfabric-', True)
    def delete_connection(self, fabric, initiator_target_map, host_name=None,
                          storage_system=None):
        """Concrete implementation of delete_connection.

        Based on zoning policy and state of each I-T pair, list of zones
        are created for deletion. The zones are either updated deleted based
        on the policy and attach/detach state of each I-T pair.

        :param fabric: Fabric name from cinder.conf file
        :param initiator_target_map: Mapping of initiator to list of targets
        """
        LOG.info("BrcdFCZoneDriver - Delete connection for fabric "
                 "%(fabric)s for I-T map: %(i_t_map)s",
                 {'fabric': fabric,
                  'i_t_map': initiator_target_map})
        zoning_policy = self.configuration.zoning_policy
        zoning_policy_fab = self.fabric_configs[fabric].safe_get(
            'zoning_policy')
        zone_name_prefix = self.fabric_configs[fabric].safe_get(
            'zone_name_prefix')
        zone_activate = self.fabric_configs[fabric].safe_get(
            'zone_activate')
        if zoning_policy_fab:
            zoning_policy = zoning_policy_fab
        LOG.info("Zoning policy for fabric %(policy)s",
                 {'policy': zoning_policy})
        conn = self._get_southbound_client(fabric)
        cfgmap_from_fabric = self._get_active_zone_set(conn)

        zone_names = []
        if cfgmap_from_fabric.get('zones'):
            zone_names = cfgmap_from_fabric['zones'].keys()

        # Based on zoning policy, get zone member list and push changes to
        # fabric. This operation could result in an update for zone config
        # with new member list or deleting zones from active cfg.
        LOG.debug("zone config from Fabric: %(cfgmap)s",
                  {'cfgmap': cfgmap_from_fabric})
        for initiator_key in initiator_target_map.keys():
            initiator = initiator_key.lower()
            formatted_initiator = utils.get_formatted_wwn(initiator)
            zone_map = {}
            zones_to_delete = []
            t_list = initiator_target_map[initiator_key]
            if zoning_policy == 'initiator-target':
                # In this case, zone needs to be deleted.
                for t in t_list:
                    target = t.lower()
                    zone_name = driver_utils.get_friendly_zone_name(
                        zoning_policy,
                        initiator,
                        target,
                        host_name,
                        storage_system,
                        zone_name_prefix,
                        SUPPORTED_CHARS)
                    LOG.debug("Zone name to delete: %(zonename)s",
                              {'zonename': zone_name})
                    if len(zone_names) > 0 and (zone_name in zone_names):
                        # delete zone.
                        LOG.debug("Added zone to delete to list: %(zonename)s",
                                  {'zonename': zone_name})
                        zones_to_delete.append(zone_name)

            elif zoning_policy == 'initiator':
                zone_members = [formatted_initiator]
                for t in t_list:
                    target = t.lower()
                    zone_members.append(utils.get_formatted_wwn(target))

                zone_name = driver_utils.get_friendly_zone_name(
                    zoning_policy,
                    initiator,
                    target,
                    host_name,
                    storage_system,
                    zone_name_prefix,
                    SUPPORTED_CHARS)

                if (zone_names and (zone_name in zone_names)):
                    # Check to see if there are other zone members
                    # in the zone besides the initiator and
                    # the targets being removed.
                    has_members = any(
                        x for x in cfgmap_from_fabric['zones'][zone_name]
                        if x not in zone_members)

                    # If there are other zone members, proceed with
                    # zone update to remove the targets.  Otherwise,
                    # delete the zone.
                    if has_members:
                        zone_members.remove(formatted_initiator)
                        # Verify that the zone members in target list
                        # are listed in zone definition.  If not, remove
                        # the zone members from the list of members
                        # to remove, otherwise switch will return error.
                        zm_list = cfgmap_from_fabric['zones'][zone_name]
                        for t in t_list:
                            formatted_target = utils.get_formatted_wwn(t)
                            if formatted_target not in zm_list:
                                zone_members.remove(formatted_target)
                        if zone_members:
                            LOG.debug("Zone members to remove: "
                                      "%(members)s", {'members': zone_members})
                            zone_map[zone_name] = zone_members
                    else:
                        zones_to_delete.append(zone_name)
            else:
                LOG.warning("Zoning policy not recognized: %(policy)s",
                            {'policy': zoning_policy})
            LOG.debug("Zone map to update: %(zonemap)s",
                      {'zonemap': zone_map})
            LOG.debug("Zone list to delete: %(zones)s",
                      {'zones': zones_to_delete})
            try:
                # Update zone membership.
                if zone_map:
                    conn.update_zones(zone_map, zone_activate,
                                      fc_zone_constants.ZONE_REMOVE,
                                      cfgmap_from_fabric)
                # Delete zones
                if zones_to_delete:
                    zone_name_string = ''
                    num_zones = len(zones_to_delete)
                    for i in range(0, num_zones):
                        if i == 0:
                            zone_name_string = (
                                '%s%s' % (
                                    zone_name_string, zones_to_delete[i]))
                        else:
                            zone_name_string = '%s;%s' % (
                                zone_name_string, zones_to_delete[i])

                    conn.delete_zones(
                        zone_name_string, zone_activate,
                        cfgmap_from_fabric)
            except (b_exception.BrocadeZoningCliException,
                    b_exception.BrocadeZoningHttpException,
                    b_exception.BrocadeZoningRestException) as brocade_ex:
                raise exception.FCZoneDriverException(brocade_ex)
            except Exception:
                msg = _("Failed to update or delete zoning "
                        "configuration.")
                LOG.exception(msg)
                raise exception.FCZoneDriverException(msg)
            finally:
                conn.cleanup()

    def get_san_context(self, target_wwn_list):
        """Lookup SAN context for visible end devices.

        Look up each SAN configured and return a map of SAN (fabric IP) to
        list of target WWNs visible to the fabric.
        """
        formatted_target_list = []
        fabric_map = {}
        fc_fabric_names = self.configuration.fc_fabric_names
        fabrics = [x.strip() for x in fc_fabric_names.split(',')]
        LOG.debug("Fabric List: %(fabrics)s", {'fabrics': fabrics})
        LOG.debug("Target WWN list: %(targetwwns)s",
                  {'targetwwns': target_wwn_list})
        if len(fabrics) > 0:
            for t in target_wwn_list:
                formatted_target_list.append(utils.get_formatted_wwn(t))
            LOG.debug("Formatted target WWN list: %(targetlist)s",
                      {'targetlist': formatted_target_list})
            for fabric_name in fabrics:
                conn = self._get_southbound_client(fabric_name)

                # Get name server data from fabric and get the targets
                # logged in.
                nsinfo = None
                try:
                    nsinfo = conn.get_nameserver_info()
                    LOG.debug("Name server info from fabric: %(nsinfo)s",
                              {'nsinfo': nsinfo})
                except (b_exception.BrocadeZoningCliException,
                        b_exception.BrocadeZoningHttpException):
                    if not conn.is_supported_firmware():
                        msg = _("Unsupported firmware on switch %s. Make sure "
                                "switch is running firmware v6.4 or higher"
                                ) % conn.switch_ip
                        LOG.exception(msg)
                        raise exception.FCZoneDriverException(msg)
                    with excutils.save_and_reraise_exception():
                        LOG.exception("Error getting name server info.")
                except Exception:
                    msg = _("Failed to get name server info.")
                    LOG.exception(msg)
                    raise exception.FCZoneDriverException(msg)
                finally:
                    conn.cleanup()
                visible_targets = [x for x in nsinfo
                                   if x in formatted_target_list]

                if visible_targets:
                    LOG.info("Filtered targets for SAN is: %(targets)s",
                             {'targets': visible_targets})
                    # getting rid of the ':' before returning
                    for idx, elem in enumerate(visible_targets):
                        visible_targets[idx] = str(
                            visible_targets[idx]).replace(':', '')
                    fabric_map[fabric_name] = visible_targets
                else:
                    LOG.debug("No targets found in the nameserver "
                              "for fabric: %(fabric)s",
                              {'fabric': fabric_name})
        LOG.debug("Return SAN context output: %(fabricmap)s",
                  {'fabricmap': fabric_map})
        return fabric_map

    def _get_active_zone_set(self, conn):
        cfgmap = None
        try:
            cfgmap = conn.get_active_zone_set()
        except (b_exception.BrocadeZoningCliException,
                b_exception.BrocadeZoningHttpException):
            if not conn.is_supported_firmware():
                msg = _("Unsupported firmware on switch %s. Make sure "
                        "switch is running firmware v6.4 or higher"
                        ) % conn.switch_ip
                LOG.error(msg)
                raise exception.FCZoneDriverException(msg)
            with excutils.save_and_reraise_exception():
                LOG.exception("Error getting name server info.")
        except Exception as e:
            msg = (_("Failed to retrieve active zoning configuration %s")
                   % six.text_type(e))
            LOG.error(msg)
            raise exception.FCZoneDriverException(msg)
        LOG.debug("Active zone set from fabric: %(cfgmap)s",
                  {'cfgmap': cfgmap})
        return cfgmap

    def _get_southbound_client(self, fabric):
        """Implementation to get SouthBound Connector.

         South bound connector will be
         dynamically selected based on the configuration

        :param fabric: fabric information
        """
        fabric_info = self.fabric_configs[fabric]
        fc_ip = fabric_info.safe_get('fc_fabric_address')
        sb_connector = fabric_info.safe_get('fc_southbound_protocol')
        if sb_connector is None:
            sb_connector = self.configuration.brcd_sb_connector
        try:
            conn_factory = importutils.import_object(
                "cinder.zonemanager.drivers.brocade."
                "brcd_fc_zone_connector_factory."
                "BrcdFCZoneFactory")
            client = conn_factory.get_connector(fabric_info,
                                                sb_connector.upper())
        except Exception:
            msg = _("Failed to create south bound connector for %s.") % fc_ip
            LOG.exception(msg)
            raise exception.FCZoneDriverException(msg)
        return client
