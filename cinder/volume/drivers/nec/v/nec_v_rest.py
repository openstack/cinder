# Copyright (C) 2021 NEC corporation
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
"""REST interface for NEC Driver."""

from oslo_config import cfg

from cinder.volume import configuration
from cinder.volume.drivers.hitachi import hbsd_rest
from cinder.volume.drivers.hitachi import hbsd_rest_api
from cinder.volume.drivers.hitachi import hbsd_rest_fc
from cinder.volume.drivers.hitachi import hbsd_rest_iscsi

COMMON_VOLUME_OPTS = [
    cfg.StrOpt(
        'nec_v_storage_id',
        default=None,
        help='Product number of the storage system.'),
    cfg.StrOpt(
        'nec_v_pool',
        default=None,
        help='Pool number or pool name of the DP pool.'),
    cfg.StrOpt(
        'nec_v_snap_pool',
        default=None,
        help='Pool number or pool name of the snapshot pool.'),
    cfg.StrOpt(
        'nec_v_ldev_range',
        default=None,
        help='Range of the LDEV numbers in the format of \'xxxx-yyyy\' that '
             'can be used by the driver. Values can be in decimal format '
             '(e.g. 1000) or in colon-separated hexadecimal format '
             '(e.g. 00:03:E8).'),
    cfg.ListOpt(
        'nec_v_target_ports',
        default=[],
        help='IDs of the storage ports used to attach volumes to the '
             'controller node. To specify multiple ports, connect them by '
             'commas (e.g. CL1-A,CL2-A).'),
    cfg.ListOpt(
        'nec_v_compute_target_ports',
        default=[],
        help='IDs of the storage ports used to attach volumes to compute '
             'nodes. To specify multiple ports, connect them by commas '
             '(e.g. CL1-A,CL2-A).'),
    cfg.BoolOpt(
        'nec_v_group_create',
        default=False,
        help='If True, the driver will create host groups or iSCSI targets on '
             'storage ports as needed.'),
    cfg.BoolOpt(
        'nec_v_group_delete',
        default=False,
        help='If True, the driver will delete host groups or iSCSI targets on '
             'storage ports as needed.'),
    cfg.IntOpt(
        'nec_v_copy_speed',
        default=3,
        min=1, max=15,
        help='Copy speed of storage system. 1 or 2 indicates '
             'low speed, 3 indicates middle speed, and a value between 4 and '
             '15 indicates high speed.'),
    cfg.IntOpt(
        'nec_v_copy_check_interval',
        default=3,
        min=1, max=600,
        help='Interval in seconds to check copying status during a volume '
             'copy.'),
    cfg.IntOpt(
        'nec_v_async_copy_check_interval',
        default=10,
        min=1, max=600,
        help='Interval in seconds to check asynchronous copying status during '
             'a copy pair deletion or data restoration.'),
]

REST_VOLUME_OPTS = [
    cfg.BoolOpt(
        'nec_v_rest_disable_io_wait',
        default=True,
        help='It may take some time to detach volume after I/O. '
             'This option will allow detaching volume to complete '
             'immediately.'),
    cfg.BoolOpt(
        'nec_v_rest_tcp_keepalive',
        default=True,
        help='Enables or disables use of REST API tcp keepalive'),
    cfg.BoolOpt(
        'nec_v_discard_zero_page',
        default=True,
        help='Enable or disable zero page reclamation in a DP-VOL.'),
    cfg.IntOpt(
        'nec_v_lun_timeout',
        default=hbsd_rest._LUN_TIMEOUT,
        help='Maximum wait time in seconds for adding a LUN to complete.'),
    cfg.IntOpt(
        'nec_v_lun_retry_interval',
        default=hbsd_rest._LUN_RETRY_INTERVAL,
        help='Retry interval in seconds for REST API adding a LUN.'),
    cfg.IntOpt(
        'nec_v_restore_timeout',
        default=hbsd_rest._RESTORE_TIMEOUT,
        help='Maximum wait time in seconds for the restore operation to '
             'complete.'),
    cfg.IntOpt(
        'nec_v_state_transition_timeout',
        default=hbsd_rest._STATE_TRANSITION_TIMEOUT,
        help='Maximum wait time in seconds for a volume transition to '
             'complete.'),
    cfg.IntOpt(
        'nec_v_lock_timeout',
        default=hbsd_rest_api._LOCK_TIMEOUT,
        help='Maximum wait time in seconds for storage to be unlocked.'),
    cfg.IntOpt(
        'nec_v_rest_timeout',
        default=hbsd_rest_api._REST_TIMEOUT,
        help='Maximum wait time in seconds for REST API execution to '
             'complete.'),
    cfg.IntOpt(
        'nec_v_extend_timeout',
        default=hbsd_rest_api._EXTEND_TIMEOUT,
        help='Maximum wait time in seconds for a volume extention to '
             'complete.'),
    cfg.IntOpt(
        'nec_v_exec_retry_interval',
        default=hbsd_rest_api._EXEC_RETRY_INTERVAL,
        help='Retry interval in seconds for REST API execution.'),
    cfg.IntOpt(
        'nec_v_rest_connect_timeout',
        default=hbsd_rest_api._DEFAULT_CONNECT_TIMEOUT,
        help='Maximum wait time in seconds for REST API connection to '
             'complete.'),
    cfg.IntOpt(
        'nec_v_rest_job_api_response_timeout',
        default=hbsd_rest_api._JOB_API_RESPONSE_TIMEOUT,
        help='Maximum wait time in seconds for a response from REST API.'),
    cfg.IntOpt(
        'nec_v_rest_get_api_response_timeout',
        default=hbsd_rest_api._GET_API_RESPONSE_TIMEOUT,
        help='Maximum wait time in seconds for a response against GET method '
             'of REST API.'),
    cfg.IntOpt(
        'nec_v_rest_server_busy_timeout',
        default=hbsd_rest_api._REST_SERVER_BUSY_TIMEOUT,
        help='Maximum wait time in seconds when REST API returns busy.'),
    cfg.IntOpt(
        'nec_v_rest_keep_session_loop_interval',
        default=hbsd_rest_api._KEEP_SESSION_LOOP_INTERVAL,
        help='Loop interval in seconds for keeping REST API session.'),
    cfg.IntOpt(
        'nec_v_rest_another_ldev_mapped_retry_timeout',
        default=hbsd_rest_api._ANOTHER_LDEV_MAPPED_RETRY_TIMEOUT,
        help='Retry time in seconds when new LUN allocation request fails.'),
    cfg.IntOpt(
        'nec_v_rest_tcp_keepidle',
        default=hbsd_rest_api._TCP_KEEPIDLE,
        help='Wait time in seconds for sending a first TCP keepalive packet.'),
    cfg.IntOpt(
        'nec_v_rest_tcp_keepintvl',
        default=hbsd_rest_api._TCP_KEEPINTVL,
        help='Interval of transmissions in seconds for TCP keepalive packet.'),
    cfg.IntOpt(
        'nec_v_rest_tcp_keepcnt',
        default=hbsd_rest_api._TCP_KEEPCNT,
        help='Maximum number of transmissions for TCP keepalive packet.'),
    cfg.ListOpt(
        'nec_v_host_mode_options',
        default=[],
        help='Host mode option for host group or iSCSI target'),
]

FC_VOLUME_OPTS = [
    cfg.BoolOpt(
        'nec_v_zoning_request',
        default=False,
        help='If True, the driver will configure FC zoning between the server '
             'and the storage system provided that FC zoning manager is '
             'enabled.'),
]

CONF = cfg.CONF
CONF.register_opts(COMMON_VOLUME_OPTS, group=configuration.SHARED_CONF_GROUP)
CONF.register_opts(REST_VOLUME_OPTS, group=configuration.SHARED_CONF_GROUP)
CONF.register_opts(FC_VOLUME_OPTS, group=configuration.SHARED_CONF_GROUP)


def update_conf(conf):
    # COMMON_VOLUME_OPTS
    conf.hitachi_storage_id = conf.nec_v_storage_id
    conf.hitachi_pool = conf.nec_v_pool
    conf.hitachi_snap_pool = conf.nec_v_snap_pool
    conf.hitachi_ldev_range = conf.nec_v_ldev_range
    conf.hitachi_target_ports = conf.nec_v_target_ports
    conf.hitachi_compute_target_ports = (
        conf.nec_v_compute_target_ports)
    conf.hitachi_group_create = conf.nec_v_group_create
    conf.hitachi_group_delete = conf.nec_v_group_delete
    conf.hitachi_copy_speed = conf.nec_v_copy_speed
    conf.hitachi_copy_check_interval = (
        conf.nec_v_copy_check_interval)
    conf.hitachi_async_copy_check_interval = (
        conf.nec_v_async_copy_check_interval)

    # REST_VOLUME_OPTS
    conf.hitachi_rest_disable_io_wait = (
        conf.nec_v_rest_disable_io_wait)
    conf.hitachi_rest_tcp_keepalive = (
        conf.nec_v_rest_tcp_keepalive)
    conf.hitachi_discard_zero_page = (
        conf.nec_v_discard_zero_page)
    conf.hitachi_lun_timeout = conf.nec_v_lun_timeout
    conf.hitachi_lun_retry_interval = (
        conf.nec_v_lun_retry_interval)
    conf.hitachi_restore_timeout = conf.nec_v_restore_timeout
    conf.hitachi_state_transition_timeout = (
        conf.nec_v_state_transition_timeout)
    conf.hitachi_lock_timeout = conf.nec_v_lock_timeout
    conf.hitachi_rest_timeout = conf.nec_v_rest_timeout
    conf.hitachi_extend_timeout = conf.nec_v_extend_timeout
    conf.hitachi_exec_retry_interval = (
        conf.nec_v_exec_retry_interval)
    conf.hitachi_rest_connect_timeout = (
        conf.nec_v_rest_connect_timeout)
    conf.hitachi_rest_job_api_response_timeout = (
        conf.nec_v_rest_job_api_response_timeout)
    conf.hitachi_rest_get_api_response_timeout = (
        conf.nec_v_rest_get_api_response_timeout)
    conf.hitachi_rest_server_busy_timeout = (
        conf.nec_v_rest_server_busy_timeout)
    conf.hitachi_rest_keep_session_loop_interval = (
        conf.nec_v_rest_keep_session_loop_interval)
    conf.hitachi_rest_another_ldev_mapped_retry_timeout = (
        conf.nec_v_rest_another_ldev_mapped_retry_timeout)
    conf.hitachi_rest_tcp_keepidle = (
        conf.nec_v_rest_tcp_keepidle)
    conf.hitachi_rest_tcp_keepintvl = (
        conf.nec_v_rest_tcp_keepintvl)
    conf.hitachi_rest_tcp_keepcnt = (
        conf.nec_v_rest_tcp_keepcnt)
    conf.hitachi_host_mode_options = (
        conf.nec_v_host_mode_options)

    return conf


class VStorageRESTFC(hbsd_rest_fc.HBSDRESTFC):
    """REST interface fibre channel class."""

    def __init__(self, conf, storage_protocol, db):
        """Initialize instance variables."""
        conf.append_config_values(COMMON_VOLUME_OPTS)
        conf.append_config_values(REST_VOLUME_OPTS)
        conf.append_config_values(FC_VOLUME_OPTS)
        super(VStorageRESTFC, self).__init__(conf, storage_protocol, db)
        self.conf = update_conf(self.conf)
        # FC_VOLUME_OPTS
        self.conf.hitachi_zoning_request = self.conf.nec_v_zoning_request


class VStorageRESTISCSI(hbsd_rest_iscsi.HBSDRESTISCSI):
    """REST interface iSCSI channel class."""

    def __init__(self, conf, storage_protocol, db):
        """Initialize instance variables."""
        conf.append_config_values(COMMON_VOLUME_OPTS)
        conf.append_config_values(REST_VOLUME_OPTS)
        super(VStorageRESTISCSI, self).__init__(conf, storage_protocol, db)
        self.conf = update_conf(self.conf)
