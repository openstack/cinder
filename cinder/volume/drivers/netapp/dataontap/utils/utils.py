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
"""
Utilities for NetApp FAS drivers.

This module contains common utilities to be used by one or more
NetApp FAS drivers to achieve the desired functionality.
"""

import json
import socket

from oslo_config import cfg
from oslo_log import log

from cinder import exception
from cinder.i18n import _
from cinder import utils
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume.drivers.netapp.dataontap.client import client_cmode
from cinder.volume.drivers.netapp import options as na_opts

LOG = log.getLogger(__name__)
CONF = cfg.CONF


def get_backend_configuration(backend_name):
    """Get a cDOT configuration object for a specific backend."""

    config_stanzas = CONF.list_all_sections()
    if backend_name not in config_stanzas:
        msg = _("Could not find backend stanza %(backend_name)s in "
                "configuration. Available stanzas are %(stanzas)s")
        params = {
            "stanzas": config_stanzas,
            "backend_name": backend_name,
        }
        raise exception.ConfigNotFound(message=msg % params)

    config = configuration.Configuration(driver.volume_opts,
                                         config_group=backend_name)
    config.append_config_values(na_opts.netapp_proxy_opts)
    config.append_config_values(na_opts.netapp_connection_opts)
    config.append_config_values(na_opts.netapp_transport_opts)
    config.append_config_values(na_opts.netapp_basicauth_opts)
    config.append_config_values(na_opts.netapp_provisioning_opts)
    config.append_config_values(na_opts.netapp_cluster_opts)
    config.append_config_values(na_opts.netapp_san_opts)
    config.append_config_values(na_opts.netapp_replication_opts)
    config.append_config_values(na_opts.netapp_support_opts)

    return config


def get_client_for_backend(backend_name, vserver_name=None):
    """Get a cDOT API client for a specific backend."""

    config = get_backend_configuration(backend_name)
    client = client_cmode.Client(
        transport_type=config.netapp_transport_type,
        username=config.netapp_login,
        password=config.netapp_password,
        hostname=config.netapp_server_hostname,
        port=config.netapp_server_port,
        vserver=vserver_name or config.netapp_vserver,
        trace=utils.TRACE_API,
        api_trace_pattern=config.netapp_api_trace_pattern)

    return client


def _build_base_ems_log_message(driver_name, app_version):

    ems_log = {
        'computer-name': socket.gethostname() or 'Cinder_node',
        'event-source': 'Cinder driver %s' % driver_name,
        'app-version': app_version,
        'category': 'provisioning',
        'log-level': '5',
        'auto-support': 'false',
    }
    return ems_log


def build_ems_log_message_0(driver_name, app_version):
    """Construct EMS Autosupport log message with deployment info."""
    ems_log = _build_base_ems_log_message(driver_name, app_version)
    ems_log['event-id'] = '0'
    ems_log['event-description'] = 'OpenStack Cinder connected to cluster node'
    return ems_log


def build_ems_log_message_1(driver_name, app_version, vserver,
                            flexvol_pools, aggregate_pools):
    """Construct EMS Autosupport log message with storage pool info."""

    message = {
        'pools': {
            'vserver': vserver,
            'aggregates': aggregate_pools,
            'flexvols': flexvol_pools,
        },
    }

    ems_log = _build_base_ems_log_message(driver_name, app_version)
    ems_log['event-id'] = '1'
    ems_log['event-description'] = json.dumps(message)
    return ems_log
