#    (c) Copyright 2012-2014 Hewlett-Packard Development Company, L.P.
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
Utility functions related to the Zone Manager.

"""
from oslo_log import log

from cinder.volume import configuration
from cinder.volume import manager
from cinder.zonemanager import fc_san_lookup_service
from cinder.zonemanager import fc_zone_manager

LOG = log.getLogger(__name__)


def create_zone_manager():
    """If zoning is enabled, build the Zone Manager."""
    config = configuration.Configuration(manager.volume_manager_opts)
    LOG.debug("Zoning mode: %s.", config.safe_get('zoning_mode'))
    if config.safe_get('zoning_mode') == 'fabric':
        LOG.debug("FC Zone Manager enabled.")
        zm = fc_zone_manager.ZoneManager()
        if zm.initialized:
            LOG.info("Using FC Zone Manager %(zm_version)s,"
                     " Driver %(drv_name)s %(drv_version)s.",
                     {'zm_version': zm.get_version(),
                      'drv_name': zm.driver.__class__.__name__,
                      'drv_version': zm.driver.get_version()})
            return zm
        else:
            LOG.debug("FC Zone Manager %(zm_version)s disabled",
                      {"zm_version": zm.get_version()})
            return None

    else:
        LOG.debug("FC Zone Manager not enabled in cinder.conf.")
        return None


def create_lookup_service():
    config = configuration.Configuration(manager.volume_manager_opts)
    LOG.debug("Zoning mode: %s.", config.safe_get('zoning_mode'))
    if config.safe_get('zoning_mode') == 'fabric':
        LOG.debug("FC Lookup Service enabled.")
        lookup = fc_san_lookup_service.FCSanLookupService()
        LOG.info("Using FC lookup service %s.", lookup.lookup_service)
        return lookup
    else:
        LOG.debug("FC Lookup Service not enabled in cinder.conf.")
        return None


def get_formatted_wwn(wwn_str):
    """Utility API that formats WWN to insert ':'."""
    if (len(wwn_str) != 16):
        return wwn_str.lower()
    else:
        return (':'.join([wwn_str[i:i + 2]
                         for i in range(0, len(wwn_str), 2)])).lower()


def add_fc_zone(connection_info):
    """Utility function to add a FC Zone."""
    if connection_info:
        vol_type = connection_info.get('driver_volume_type', None)
        if vol_type == 'fibre_channel':
            if connection_info['data'].get('initiator_target_map'):
                zm = create_zone_manager()
                if zm:
                    LOG.debug("add_fc_zone connection info: %(conninfo)s.",
                              {'conninfo': connection_info})
                    zm.add_connection(connection_info)


def remove_fc_zone(connection_info):
    """Utility function for FC drivers to remove zone."""
    if connection_info:
        vol_type = connection_info.get('driver_volume_type', None)
        if vol_type == 'fibre_channel':
            if connection_info['data'].get('initiator_target_map'):
                zm = create_zone_manager()
                if zm:
                    LOG.debug("remove_fc_zone connection info: %(conninfo)s.",
                              {'conninfo': connection_info})
                    zm.delete_connection(connection_info)
