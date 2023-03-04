# Copyright (C) 2022, 2023, Hewlett Packard Enterprise, Ltd.
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
"""REST interface for Hewlett Packard Enterprise Driver."""

from oslo_config import cfg

from cinder.volume import configuration
from cinder.volume.drivers.hitachi import hbsd_rest
from cinder.volume.drivers.hitachi import hbsd_rest_api
from cinder.volume.drivers.hitachi import hbsd_rest_fc
from cinder.volume.drivers.hitachi import hbsd_rest_iscsi

COMMON_VOLUME_OPTS = [
    cfg.StrOpt(
        'hpexp_storage_id',
        default=None,
        help='Product number of the storage system.'),
    cfg.ListOpt(
        'hpexp_pools',
        default=[],
        deprecated_name='hpexp_pool',
        help='Pool number[s] or pool name[s] of the THP pool.'),
    cfg.StrOpt(
        'hpexp_snap_pool',
        default=None,
        help='Pool number or pool name of the snapshot pool.'),
    cfg.StrOpt(
        'hpexp_ldev_range',
        default=None,
        help='Range of the LDEV numbers in the format of \'xxxx-yyyy\' that '
             'can be used by the driver. Values can be in decimal format '
             '(e.g. 1000) or in colon-separated hexadecimal format '
             '(e.g. 00:03:E8).'),
    cfg.ListOpt(
        'hpexp_target_ports',
        default=[],
        help='IDs of the storage ports used to attach volumes to the '
             'controller node. To specify multiple ports, connect them by '
             'commas (e.g. CL1-A,CL2-A).'),
    cfg.ListOpt(
        'hpexp_compute_target_ports',
        default=[],
        help='IDs of the storage ports used to attach volumes to compute '
             'nodes. To specify multiple ports, connect them by commas '
             '(e.g. CL1-A,CL2-A).'),
    cfg.BoolOpt(
        'hpexp_group_create',
        default=False,
        help='If True, the driver will create host groups or iSCSI targets on '
             'storage ports as needed.'),
    cfg.BoolOpt(
        'hpexp_group_delete',
        default=False,
        help='If True, the driver will delete host groups or iSCSI targets on '
             'storage ports as needed.'),
    cfg.IntOpt(
        'hpexp_copy_speed',
        default=3,
        min=1, max=15,
        help='Copy speed of storage system. 1 or 2 indicates '
             'low speed, 3 indicates middle speed, and a value between 4 and '
             '15 indicates high speed.'),
    cfg.IntOpt(
        'hpexp_copy_check_interval',
        default=3,
        min=1, max=600,
        help='Interval in seconds to check copy'),
    cfg.IntOpt(
        'hpexp_async_copy_check_interval',
        default=10,
        min=1, max=600,
        help='Interval in seconds to check copy asynchronously'),
]

REST_VOLUME_OPTS = [
    cfg.BoolOpt(
        'hpexp_rest_disable_io_wait',
        default=True,
        help='It may take some time to detach volume after I/O. '
             'This option will allow detaching volume to complete '
             'immediately.'),
    cfg.BoolOpt(
        'hpexp_rest_tcp_keepalive',
        default=True,
        help='Enables or disables use of REST API tcp keepalive'),
    cfg.BoolOpt(
        'hpexp_discard_zero_page',
        default=True,
        help='Enable or disable zero page reclamation in a THP V-VOL.'),
    cfg.IntOpt(
        'hpexp_lun_timeout',
        default=hbsd_rest._LUN_TIMEOUT,
        help='Maximum wait time in seconds for adding a LUN to complete.'),
    cfg.IntOpt(
        'hpexp_lun_retry_interval',
        default=hbsd_rest._LUN_RETRY_INTERVAL,
        help='Retry interval in seconds for REST API adding a LUN.'),
    cfg.IntOpt(
        'hpexp_restore_timeout',
        default=hbsd_rest._RESTORE_TIMEOUT,
        help='Maximum wait time in seconds for the restore operation to '
             'complete.'),
    cfg.IntOpt(
        'hpexp_state_transition_timeout',
        default=hbsd_rest._STATE_TRANSITION_TIMEOUT,
        help='Maximum wait time in seconds for a volume transition to '
             'complete.'),
    cfg.IntOpt(
        'hpexp_lock_timeout',
        default=hbsd_rest_api._LOCK_TIMEOUT,
        help='Maximum wait time in seconds for storage to be unlocked.'),
    cfg.IntOpt(
        'hpexp_rest_timeout',
        default=hbsd_rest_api._REST_TIMEOUT,
        help='Maximum wait time in seconds for REST API execution to '
             'complete.'),
    cfg.IntOpt(
        'hpexp_extend_timeout',
        default=hbsd_rest_api._EXTEND_TIMEOUT,
        help='Maximum wait time in seconds for a volume extention to '
             'complete.'),
    cfg.IntOpt(
        'hpexp_exec_retry_interval',
        default=hbsd_rest_api._EXEC_RETRY_INTERVAL,
        help='Retry interval in seconds for REST API execution.'),
    cfg.IntOpt(
        'hpexp_rest_connect_timeout',
        default=hbsd_rest_api._DEFAULT_CONNECT_TIMEOUT,
        help='Maximum wait time in seconds for REST API connection to '
             'complete.'),
    cfg.IntOpt(
        'hpexp_rest_job_api_response_timeout',
        default=hbsd_rest_api._JOB_API_RESPONSE_TIMEOUT,
        help='Maximum wait time in seconds for a response from REST API.'),
    cfg.IntOpt(
        'hpexp_rest_get_api_response_timeout',
        default=hbsd_rest_api._GET_API_RESPONSE_TIMEOUT,
        help='Maximum wait time in seconds for a response against GET method '
             'of REST API.'),
    cfg.IntOpt(
        'hpexp_rest_server_busy_timeout',
        default=hbsd_rest_api._REST_SERVER_BUSY_TIMEOUT,
        help='Maximum wait time in seconds when REST API returns busy.'),
    cfg.IntOpt(
        'hpexp_rest_keep_session_loop_interval',
        default=hbsd_rest_api._KEEP_SESSION_LOOP_INTERVAL,
        help='Loop interval in seconds for keeping REST API session.'),
    cfg.IntOpt(
        'hpexp_rest_another_ldev_mapped_retry_timeout',
        default=hbsd_rest_api._ANOTHER_LDEV_MAPPED_RETRY_TIMEOUT,
        help='Retry time in seconds when new LUN allocation request fails.'),
    cfg.IntOpt(
        'hpexp_rest_tcp_keepidle',
        default=hbsd_rest_api._TCP_KEEPIDLE,
        help='Wait time in seconds for sending a first TCP keepalive packet.'),
    cfg.IntOpt(
        'hpexp_rest_tcp_keepintvl',
        default=hbsd_rest_api._TCP_KEEPINTVL,
        help='Interval of transmissions in seconds for TCP keepalive packet.'),
    cfg.IntOpt(
        'hpexp_rest_tcp_keepcnt',
        default=hbsd_rest_api._TCP_KEEPCNT,
        help='Maximum number of transmissions for TCP keepalive packet.'),
    cfg.ListOpt(
        'hpexp_host_mode_options',
        default=[],
        help='Host mode option for host group or iSCSI target.'),
]

FC_VOLUME_OPTS = [
    cfg.BoolOpt(
        'hpexp_zoning_request',
        default=False,
        help='If True, the driver will configure FC zoning between the server '
             'and the storage system provided that FC zoning manager is '
             'enabled.'),
]

CONF = cfg.CONF
CONF.register_opts(COMMON_VOLUME_OPTS, group=configuration.SHARED_CONF_GROUP)
CONF.register_opts(REST_VOLUME_OPTS, group=configuration.SHARED_CONF_GROUP)
CONF.register_opts(FC_VOLUME_OPTS, group=configuration.SHARED_CONF_GROUP)


class HPEXPRESTFC(hbsd_rest_fc.HBSDRESTFC):
    """REST interface fibre channel class for

    Hewlett Packard Enterprise Driver.

    """

    def __init__(self, conf, storage_protocol, db):
        """Initialize instance variables."""
        conf.append_config_values(COMMON_VOLUME_OPTS)
        conf.append_config_values(REST_VOLUME_OPTS)
        conf.append_config_values(FC_VOLUME_OPTS)
        super(HPEXPRESTFC, self).__init__(conf, storage_protocol, db)
        self._update_conf()

    def _update_conf(self):
        """Update configuration"""
        # COMMON_VOLUME_OPTS
        self.conf.hitachi_storage_id = self.conf.hpexp_storage_id
        self.conf.hitachi_pools = self.conf.hpexp_pools
        self.conf.hitachi_snap_pool = self.conf.hpexp_snap_pool
        self.conf.hitachi_ldev_range = self.conf.hpexp_ldev_range
        self.conf.hitachi_target_ports = self.conf.hpexp_target_ports
        self.conf.hitachi_compute_target_ports = (
            self.conf.hpexp_compute_target_ports)
        self.conf.hitachi_group_create = self.conf.hpexp_group_create
        self.conf.hitachi_group_delete = self.conf.hpexp_group_delete
        self.conf.hitachi_copy_speed = self.conf.hpexp_copy_speed
        self.conf.hitachi_copy_check_interval = (
            self.conf.hpexp_copy_check_interval)
        self.conf.hitachi_async_copy_check_interval = (
            self.conf.hpexp_async_copy_check_interval)

        # REST_VOLUME_OPTS
        self.conf.hitachi_rest_disable_io_wait = (
            self.conf.hpexp_rest_disable_io_wait)
        self.conf.hitachi_rest_tcp_keepalive = (
            self.conf.hpexp_rest_tcp_keepalive)
        self.conf.hitachi_discard_zero_page = (
            self.conf.hpexp_discard_zero_page)
        self.conf.hitachi_lun_timeout = self.conf.hpexp_lun_timeout
        self.conf.hitachi_lun_retry_interval = (
            self.conf.hpexp_lun_retry_interval)
        self.conf.hitachi_restore_timeout = self.conf.hpexp_restore_timeout
        self.conf.hitachi_state_transition_timeout = (
            self.conf.hpexp_state_transition_timeout)
        self.conf.hitachi_lock_timeout = self.conf.hpexp_lock_timeout
        self.conf.hitachi_rest_timeout = self.conf.hpexp_rest_timeout
        self.conf.hitachi_extend_timeout = self.conf.hpexp_extend_timeout
        self.conf.hitachi_exec_retry_interval = (
            self.conf.hpexp_exec_retry_interval)
        self.conf.hitachi_rest_connect_timeout = (
            self.conf.hpexp_rest_connect_timeout)
        self.conf.hitachi_rest_job_api_response_timeout = (
            self.conf.hpexp_rest_job_api_response_timeout)
        self.conf.hitachi_rest_get_api_response_timeout = (
            self.conf.hpexp_rest_get_api_response_timeout)
        self.conf.hitachi_rest_server_busy_timeout = (
            self.conf.hpexp_rest_server_busy_timeout)
        self.conf.hitachi_rest_keep_session_loop_interval = (
            self.conf.hpexp_rest_keep_session_loop_interval)
        self.conf.hitachi_rest_another_ldev_mapped_retry_timeout = (
            self.conf.hpexp_rest_another_ldev_mapped_retry_timeout)
        self.conf.hitachi_rest_tcp_keepidle = (
            self.conf.hpexp_rest_tcp_keepidle)
        self.conf.hitachi_rest_tcp_keepintvl = (
            self.conf.hpexp_rest_tcp_keepintvl)
        self.conf.hitachi_rest_tcp_keepcnt = (
            self.conf.hpexp_rest_tcp_keepcnt)
        self.conf.hitachi_host_mode_options = (
            self.conf.hpexp_host_mode_options)

        # FC_VOLUME_OPTS
        self.conf.hitachi_zoning_request = self.conf.hpexp_zoning_request


class HPEXPRESTISCSI(hbsd_rest_iscsi.HBSDRESTISCSI):
    """REST interface iSCSI class for Hewlett Packard Enterprise Driver."""

    def __init__(self, conf, storage_protocol, db):
        """Initialize instance variables."""
        conf.append_config_values(COMMON_VOLUME_OPTS)
        conf.append_config_values(REST_VOLUME_OPTS)
        super(HPEXPRESTISCSI, self).__init__(conf, storage_protocol, db)
        self._update_conf()

    def _update_conf(self):
        """Update configuration"""
        # COMMON_VOLUME_OPTS
        self.conf.hitachi_storage_id = self.conf.hpexp_storage_id
        self.conf.hitachi_pools = self.conf.hpexp_pools
        self.conf.hitachi_snap_pool = self.conf.hpexp_snap_pool
        self.conf.hitachi_ldev_range = self.conf.hpexp_ldev_range
        self.conf.hitachi_target_ports = self.conf.hpexp_target_ports
        self.conf.hitachi_compute_target_ports = (
            self.conf.hpexp_compute_target_ports)
        self.conf.hitachi_group_create = self.conf.hpexp_group_create
        self.conf.hitachi_group_delete = self.conf.hpexp_group_delete
        self.conf.hitachi_copy_speed = self.conf.hpexp_copy_speed
        self.conf.hitachi_copy_check_interval = (
            self.conf.hpexp_copy_check_interval)
        self.conf.hitachi_async_copy_check_interval = (
            self.conf.hpexp_async_copy_check_interval)

        # REST_VOLUME_OPTS
        self.conf.hitachi_rest_disable_io_wait = (
            self.conf.hpexp_rest_disable_io_wait)
        self.conf.hitachi_rest_tcp_keepalive = (
            self.conf.hpexp_rest_tcp_keepalive)
        self.conf.hitachi_discard_zero_page = (
            self.conf.hpexp_discard_zero_page)
        self.conf.hitachi_lun_timeout = self.conf.hpexp_lun_timeout
        self.conf.hitachi_lun_retry_interval = (
            self.conf.hpexp_lun_retry_interval)
        self.conf.hitachi_restore_timeout = self.conf.hpexp_restore_timeout
        self.conf.hitachi_state_transition_timeout = (
            self.conf.hpexp_state_transition_timeout)
        self.conf.hitachi_lock_timeout = self.conf.hpexp_lock_timeout
        self.conf.hitachi_rest_timeout = self.conf.hpexp_rest_timeout
        self.conf.hitachi_extend_timeout = self.conf.hpexp_extend_timeout
        self.conf.hitachi_exec_retry_interval = (
            self.conf.hpexp_exec_retry_interval)
        self.conf.hitachi_rest_connect_timeout = (
            self.conf.hpexp_rest_connect_timeout)
        self.conf.hitachi_rest_job_api_response_timeout = (
            self.conf.hpexp_rest_job_api_response_timeout)
        self.conf.hitachi_rest_get_api_response_timeout = (
            self.conf.hpexp_rest_get_api_response_timeout)
        self.conf.hitachi_rest_server_busy_timeout = (
            self.conf.hpexp_rest_server_busy_timeout)
        self.conf.hitachi_rest_keep_session_loop_interval = (
            self.conf.hpexp_rest_keep_session_loop_interval)
        self.conf.hitachi_rest_another_ldev_mapped_retry_timeout = (
            self.conf.hpexp_rest_another_ldev_mapped_retry_timeout)
        self.conf.hitachi_rest_tcp_keepidle = (
            self.conf.hpexp_rest_tcp_keepidle)
        self.conf.hitachi_rest_tcp_keepintvl = (
            self.conf.hpexp_rest_tcp_keepintvl)
        self.conf.hitachi_rest_tcp_keepcnt = (
            self.conf.hpexp_rest_tcp_keepcnt)
        self.conf.hitachi_host_mode_options = (
            self.conf.hpexp_host_mode_options)
