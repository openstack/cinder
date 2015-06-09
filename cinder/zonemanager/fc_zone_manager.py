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
ZoneManager is responsible to manage access control using FC zoning
when zoning mode is set as 'fabric'.
ZoneManager provides interfaces to add connection and remove connection
for given initiator and target list associated with a FC volume attach and
detach operation.

**Related Flags**

:zone_driver:  Used by:class:`ZoneManager`.
    Defaults to
    `cinder.zonemanager.drivers.brocade.brcd_fc_zone_driver.BrcdFCZoneDriver`
:zoning_policy: Used by: class: 'ZoneManager'. Defaults to 'none'

"""

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import importutils
import six

from cinder import exception
from cinder.i18n import _, _LI
from cinder.volume import configuration as config
from cinder.zonemanager import fc_common

LOG = logging.getLogger(__name__)

zone_manager_opts = [
    cfg.StrOpt('zone_driver',
               default='cinder.zonemanager.drivers.brocade.brcd_fc_zone_driver'
               '.BrcdFCZoneDriver',
               help='FC Zone Driver responsible for zone management'),
    cfg.StrOpt('zoning_policy',
               default='initiator-target',
               help='Zoning policy configured by user; valid values include '
               '"initiator-target" or "initiator"'),
    cfg.StrOpt('fc_fabric_names',
               default=None,
               help='Comma separated list of Fibre Channel fabric names.'
               ' This list of names is used to retrieve other SAN credentials'
               ' for connecting to each SAN fabric'),
    cfg.StrOpt('fc_san_lookup_service',
               default='cinder.zonemanager.drivers.brocade'
               '.brcd_fc_san_lookup_service.BrcdFCSanLookupService',
               help='FC SAN Lookup Service'),
]

CONF = cfg.CONF
CONF.register_opts(zone_manager_opts, 'fc-zone-manager')


class ZoneManager(fc_common.FCCommon):
    """Manages Connection control during attach/detach.

       Version History:
           1.0 - Initial version
           1.0.1 - Added __new__ for singleton

    """

    VERSION = "1.0.1"
    driver = None
    fabric_names = []

    def __new__(class_, *args, **kwargs):
        if not hasattr(class_, "_instance"):
            class_._instance = object.__new__(class_, *args, **kwargs)
        return class_._instance

    def __init__(self, **kwargs):
        """Load the driver from the one specified in args, or from flags."""
        super(ZoneManager, self).__init__(**kwargs)

        self.configuration = config.Configuration(zone_manager_opts,
                                                  'fc-zone-manager')

        self._build_driver()

    def _build_driver(self):
        zone_driver = self.configuration.zone_driver
        LOG.debug("Zone Driver from config: {%s}", zone_driver)

        # Initialize vendor specific implementation of  FCZoneDriver
        self.driver = importutils.import_object(
            zone_driver,
            configuration=self.configuration)

    def get_zoning_state_ref_count(self, initiator_wwn, target_wwn):
        """Zone management state check.

        Performs state check for given I-T pair to return the current count of
        active attach for the pair.
        """
        # TODO(sk): ref count state management
        count = 0
        # check the state for I-T pair
        return count

    def add_connection(self, initiator_target_map):
        """Add connection control.

        Adds connection control for the given initiator target map.
        initiator_target_map - each initiator WWN mapped to a list of one
        or more target WWN:
        eg:
        {
            '10008c7cff523b01': ['20240002ac000a50', '20240002ac000a40']
        }
        """
        connected_fabric = None
        try:
            for initiator in initiator_target_map.keys():
                target_list = initiator_target_map[initiator]
                LOG.debug("Target List: %s", target_list)

                # get SAN context for the target list
                fabric_map = self.get_san_context(target_list)
                LOG.debug("Fabric Map after context lookup: %s", fabric_map)
                # iterate over each SAN and apply connection control
                for fabric in fabric_map.keys():
                    connected_fabric = fabric
                    t_list = fabric_map[fabric]
                    # get valid I-T map to add connection control
                    i_t_map = {initiator: t_list}
                    valid_i_t_map = self.get_valid_initiator_target_map(
                        i_t_map, True)
                    LOG.info(_LI("Final filtered map for fabric: %s"),
                             valid_i_t_map)

                    # Call driver to add connection control
                    self.driver.add_connection(fabric, valid_i_t_map)

            LOG.info(_LI("Add Connection: Finished iterating "
                         "over all target list"))
        except Exception as e:
            msg = _("Failed adding connection for fabric=%(fabric)s: "
                    "Error: %(err)s") % {'fabric': connected_fabric,
                                         'err': six.text_type(e)}
            LOG.error(msg)
            raise exception.ZoneManagerException(reason=msg)

    def delete_connection(self, initiator_target_map):
        """Delete connection.

        Updates/deletes connection control for the given initiator target map.
        initiator_target_map - each initiator WWN mapped to a list of one
        or more target WWN:
        eg:
        {
            '10008c7cff523b01': ['20240002ac000a50', '20240002ac000a40']
        }
        """
        connected_fabric = None
        try:
            for initiator in initiator_target_map.keys():
                target_list = initiator_target_map[initiator]
                LOG.info(_LI("Delete connection Target List: %s"),
                         target_list)

                # get SAN context for the target list
                fabric_map = self.get_san_context(target_list)
                LOG.debug("Delete connection Fabric Map from SAN "
                          "context: %s", fabric_map)

                # iterate over each SAN and apply connection control
                for fabric in fabric_map.keys():
                    connected_fabric = fabric
                    t_list = fabric_map[fabric]
                    # get valid I-T map to add connection control
                    i_t_map = {initiator: t_list}
                    valid_i_t_map = self.get_valid_initiator_target_map(
                        i_t_map, False)
                    LOG.info(_LI("Final filtered map for delete "
                                 "connection: %s"), valid_i_t_map)

                    # Call driver to delete connection control
                    if len(valid_i_t_map) > 0:
                        self.driver.delete_connection(fabric, valid_i_t_map)

            LOG.debug("Delete Connection - Finished iterating over all"
                      " target list")
        except Exception as e:
            msg = _("Failed removing connection for fabric=%(fabric)s: "
                    "Error: %(err)s") % {'fabric': connected_fabric,
                                         'err': six.text_type(e)}
            LOG.error(msg)
            raise exception.ZoneManagerException(reason=msg)

    def get_san_context(self, target_wwn_list):
        """SAN lookup for end devices.

        Look up each SAN configured and return a map of SAN (fabric IP)
        to list of target WWNs visible to the fabric.
        """
        fabric_map = self.driver.get_san_context(target_wwn_list)
        LOG.debug("Got SAN context: %s", fabric_map)
        return fabric_map

    def get_valid_initiator_target_map(self, initiator_target_map,
                                       add_control):
        """Reference count check for end devices.

        Looks up the reference count for each initiator-target pair from the
        map and returns a filtered list based on the operation type
        add_control - operation type can be true for add connection control
        and false for remove connection control
        """
        filtered_i_t_map = {}
        for initiator in initiator_target_map.keys():
            t_list = initiator_target_map[initiator]
            for target in t_list:
                count = self.get_zoning_state_ref_count(initiator, target)
                if add_control:
                    if count > 0:
                        t_list.remove(target)
                    # update count = count + 1
                else:
                    if count > 1:
                        t_list.remove(target)
                    # update count = count - 1
            if t_list:
                filtered_i_t_map[initiator] = t_list
            else:
                LOG.info(_LI("No targets to add or remove connection for "
                             "I: %s"), initiator)
        return filtered_i_t_map
