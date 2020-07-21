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

from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import importutils

from cinder import exception
from cinder.i18n import _
from cinder.zonemanager.drivers.brocade import brcd_fabric_opts as fabric_opts
from cinder.zonemanager import fc_san_lookup_service as fc_service
from cinder.zonemanager import utils as fczm_utils

LOG = logging.getLogger(__name__)


class BrcdFCSanLookupService(fc_service.FCSanLookupService):
    """The SAN lookup service that talks to Brocade switches.

    Version History:
        1.0.0 - Initial version
        1.1 - Add support to use config option for switch southbound protocol
        1.2 - Fix open sessions issue

    """

    VERSION = "1.2"

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
        :returns: List -- device wwn map in following format

        .. code-block:: default

            {
                <San name>: {
                    'initiator_port_wwn_list':
                    ('200000051e55a100', '200000051e55a121'..)
                    'target_port_wwn_list':
                    ('100000051e55a100', '100000051e55a121'..)
                }
            }

        :raises Exception: when connection to fabric is failed
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
                formatted_target_list.append(fczm_utils.get_formatted_wwn(t))

            for i in initiator_wwn_list:
                formatted_initiator_list.append(fczm_utils.
                                                get_formatted_wwn(i))

            for fabric_name in fabrics:
                fabric_ip = self.fabric_configs[fabric_name].safe_get(
                    'fc_fabric_address')

                # Get name server data from fabric and find the targets
                # logged in
                nsinfo = ''
                conn = None
                try:
                    LOG.debug("Getting name server data for "
                              "fabric %s", fabric_ip)
                    conn = self._get_southbound_client(fabric_name)
                    nsinfo = conn.get_nameserver_info()
                except exception.FCSanLookupServiceException:
                    with excutils.save_and_reraise_exception():
                        LOG.error("Failed collecting name server info from"
                                  " fabric %s", fabric_ip)
                except Exception as e:
                    msg = _("Connection failed "
                            "for %(fabric)s with error: %(err)s"
                            ) % {'fabric': fabric_ip, 'err': e}
                    LOG.error(msg)
                    raise exception.FCSanLookupServiceException(message=msg)
                finally:
                    if conn:
                        conn.cleanup()

                LOG.debug("Lookup service:nsinfo-%s", nsinfo)
                LOG.debug("Lookup service:initiator list from "
                          "caller-%s", formatted_initiator_list)
                LOG.debug("Lookup service:target list from "
                          "caller-%s", formatted_target_list)
                visible_targets = [x for x in nsinfo
                                   if x in formatted_target_list]
                visible_initiators = [x for x in nsinfo
                                      if x in formatted_initiator_list]

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
