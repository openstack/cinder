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
import logging

from oslo_log import log

from cinder.i18n import _LI, _LW
from cinder.volume import configuration
from cinder.volume import manager
from cinder.zonemanager import fc_san_lookup_service
from cinder.zonemanager import fc_zone_manager

LOG = log.getLogger(__name__)
LOG.logger.setLevel(logging.DEBUG)


def create_zone_manager():
    """If zoning is enabled, build the Zone Manager."""
    config = configuration.Configuration(manager.volume_manager_opts)
    LOG.debug("Zoning mode: %s", config.safe_get('zoning_mode'))
    if config.safe_get('zoning_mode') == 'fabric':
        LOG.debug("FC Zone Manager enabled.")
        zm = fc_zone_manager.ZoneManager()
        LOG.info(_LI("Using FC Zone Manager %(zm_version)s,"
                     " Driver %(drv_name)s %(drv_version)s."),
                 {'zm_version': zm.get_version(),
                  'drv_name': zm.driver.__class__.__name__,
                  'drv_version': zm.driver.get_version()})
        return zm
    else:
        LOG.debug("FC Zone Manager not enabled in cinder.conf.")
        return None


def create_lookup_service():
    config = configuration.Configuration(manager.volume_manager_opts)
    LOG.debug("Zoning mode: %s", config.safe_get('zoning_mode'))
    if config.safe_get('zoning_mode') == 'fabric':
        LOG.debug("FC Lookup Service enabled.")
        lookup = fc_san_lookup_service.FCSanLookupService()
        LOG.info(_LI("Using FC lookup service %s"), lookup.lookup_service)
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


def AddFCZone(initialize_connection):
    """Decorator to add a FC Zone."""
    def decorator(self, *args, **kwargs):
        conn_info = initialize_connection(self, *args, **kwargs)
        if not conn_info:
            LOG.warning(_LW("Driver didn't return connection info, "
                            "can't add zone."))
            return None

        vol_type = conn_info.get('driver_volume_type', None)
        if vol_type == 'fibre_channel':

            if 'initiator_target_map' in conn_info['data']:
                init_target_map = conn_info['data']['initiator_target_map']
                zm = create_zone_manager()
                if zm:
                    LOG.debug("Add FC Zone for mapping '%s'.",
                              init_target_map)
                    zm.add_connection(init_target_map)

        return conn_info

    return decorator


def RemoveFCZone(terminate_connection):
    """Decorator for FC drivers to remove zone."""
    def decorator(self, *args, **kwargs):
        conn_info = terminate_connection(self, *args, **kwargs)
        if not conn_info:
            LOG.warning(_LW("Driver didn't return connection info from "
                            "terminate_connection call."))
            return None

        vol_type = conn_info.get('driver_volume_type', None)
        if vol_type == 'fibre_channel':

            if 'initiator_target_map' in conn_info['data']:
                init_target_map = conn_info['data']['initiator_target_map']
                zm = create_zone_manager()
                if zm:
                    LOG.debug("Remove FC Zone for mapping '%s'.",
                              init_target_map)
                    zm.delete_connection(init_target_map)

        return conn_info

    return decorator
