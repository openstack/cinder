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
from oslo_log import log as logging

from cinder import exception
from cinder.i18n import _
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume.drivers.netapp.dataontap.client import client_cmode
from cinder.volume.drivers.netapp.dataontap.client import client_cmode_rest
from cinder.volume.drivers.netapp.dataontap.client \
    import client_cmode_rest_asar2
from cinder.volume.drivers.netapp import options as na_opts
from cinder.volume import volume_utils

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


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
    config.append_config_values(na_opts.netapp_certificateauth_opts)
    config.append_config_values(na_opts.netapp_provisioning_opts)
    config.append_config_values(na_opts.netapp_cluster_opts)
    config.append_config_values(na_opts.netapp_san_opts)
    config.append_config_values(na_opts.netapp_replication_opts)
    config.append_config_values(na_opts.netapp_support_opts)
    config.append_config_values(na_opts.netapp_migration_opts)

    return config


def get_client_for_backend(backend_name, vserver_name=None, force_rest=False):
    """Get a cDOT API client for a specific backend."""

    config = get_backend_configuration(backend_name)

    # Determine if disaggregated platform should be used
    # Parameter takes precedence over config setting
    is_disaggregated = config.netapp_disaggregated_platform

    # ZAPI clients are not supported for ASAr2 platform.
    # We are forcing the client to be REST client for ASAr2.
    if is_disaggregated:
        force_rest = True

    if config.netapp_use_legacy_client and not force_rest:
        client = client_cmode.Client(
            transport_type=config.netapp_transport_type,
            ssl_cert_path=config.netapp_ssl_cert_path,
            username=config.netapp_login,
            password=config.netapp_password,
            hostname=config.netapp_server_hostname,
            private_key_file=config.netapp_private_key_file,
            certificate_file=config.netapp_certificate_file,
            ca_certificate_file=config.netapp_ca_certificate_file,
            certificate_host_validation=
            config.netapp_certificate_host_validation,
            port=config.netapp_server_port,
            vserver=vserver_name or config.netapp_vserver,
            trace=volume_utils.TRACE_API,
            api_trace_pattern=config.netapp_api_trace_pattern)
    else:
        # Check if ASA r2 disaggregated platform is enabled
        if is_disaggregated:
            client = client_cmode_rest_asar2.RestClientASAr2(
                transport_type=config.netapp_transport_type,
                ssl_cert_path=config.netapp_ssl_cert_path,
                username=config.netapp_login,
                password=config.netapp_password,
                hostname=config.netapp_server_hostname,
                private_key_file=config.netapp_private_key_file,
                certificate_file=config.netapp_certificate_file,
                ca_certificate_file=config.netapp_ca_certificate_file,
                certificate_host_validation=
                config.netapp_certificate_host_validation,
                port=config.netapp_server_port,
                vserver=vserver_name or config.netapp_vserver,
                trace=volume_utils.TRACE_API,
                api_trace_pattern=config.netapp_api_trace_pattern,
                async_rest_timeout=config.netapp_async_rest_timeout,
                is_disaggregated=is_disaggregated)
        else:
            client = client_cmode_rest.RestClient(
                transport_type=config.netapp_transport_type,
                ssl_cert_path=config.netapp_ssl_cert_path,
                username=config.netapp_login,
                password=config.netapp_password,
                hostname=config.netapp_server_hostname,
                private_key_file=config.netapp_private_key_file,
                certificate_file=config.netapp_certificate_file,
                ca_certificate_file=config.netapp_ca_certificate_file,
                certificate_host_validation=
                config.netapp_certificate_host_validation,
                port=config.netapp_server_port,
                vserver=vserver_name or config.netapp_vserver,
                trace=volume_utils.TRACE_API,
                api_trace_pattern=config.netapp_api_trace_pattern,
                async_rest_timeout=config.netapp_async_rest_timeout)
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


def get_cluster_to_pool_map(client):
    """Get the cluster name for ASA r2 systems.

    For ASA r2 systems, instead of using flexvols, we use the cluster name
    as the pool. The map is of the format suitable for seeding the storage
    service catalog: {<cluster_name> : {'pool_name': <cluster_name>}}

    :param client: NetApp client instance to retrieve cluster information
    :returns: Dictionary mapping cluster names to pool information
    :raises: InvalidConfigurationValue if cluster is not disaggregated
    """
    pools = {}

    cluster_info = client.get_cluster_info()

    # Check if cluster info is missing or cluster is not disaggregated (ASA r2)
    if not cluster_info.get('disaggregated', False):
        LOG.error("Cluster is not a disaggregated (ASA r2) platform. ")
        raise exception.InvalidConfigurationValue(
            option='disaggregated',
            value=cluster_info.get('disaggregated', None)
        )

    cluster_name = cluster_info['name']
    LOG.debug("Found ASA r2 cluster: %s", cluster_name)
    pools[cluster_name] = {'pool_name': cluster_name}

    msg_args = {
        'cluster': cluster_name,
    }
    msg = "ASA r2 cluster '%(cluster)s' added as pool"
    LOG.debug(msg, msg_args)

    return pools
