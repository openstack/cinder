# Copyright (C) 2021 NEC corporation
#
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
"""Unit tests for NEC Driver."""

from unittest import mock

from oslo_config import cfg
import requests

from cinder import context as cinder_context
from cinder import db
from cinder.tests.unit import fake_volume
from cinder.tests.unit import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.hitachi import hbsd_rest
from cinder.volume.drivers.hitachi import hbsd_rest_api
from cinder.volume.drivers.nec.v import nec_v_iscsi
from cinder.volume.drivers.nec.v import nec_v_rest
from cinder.volume import volume_utils

# Configuration parameter values
CONFIG_MAP = {
    'serial': '886000123456',
    'my_ip': '127.0.0.1',
    'rest_server_ip_addr': '172.16.18.108',
    'rest_server_ip_port': '23451',
    'port_id': 'CL1-A',
    'host_grp_name': 'NEC-127.0.0.1',
    'host_mode': 'LINUX/IRIX',
    'host_iscsi_name': 'iqn.nec-test-host',
    'target_iscsi_name': 'iqn.nec-test-target',
    'user_id': 'user',
    'user_pass': 'password',
    'ipv4Address': '111.22.333.44',
    'tcpPort': '5555',
    'auth_user': 'auth_user',
    'auth_password': 'auth_password',
}

DEFAULT_CONNECTOR = {
    'host': 'host',
    'ip': CONFIG_MAP['my_ip'],
    'initiator': CONFIG_MAP['host_iscsi_name'],
    'multipath': False,
}

# Dummy response for REST API
POST_SESSIONS_RESULT = {
    "token": "b74777a3-f9f0-4ea8-bd8f-09847fac48d3",
    "sessionId": 0,
}

GET_PORTS_RESULT = {
    "data": [
        {
            "portId": CONFIG_MAP['port_id'],
            "portType": "ISCSI",
            "portAttributes": [
                "TAR",
                "MCU",
                "RCU",
                "ELUN"
            ],
            "portSpeed": "AUT",
            "loopId": "00",
            "fabricMode": False,
            "lunSecuritySetting": True,
        },
    ],
}

GET_PORT_RESULT = {
    "ipv4Address": CONFIG_MAP['ipv4Address'],
    "tcpPort": CONFIG_MAP['tcpPort'],
}

GET_HOST_ISCSIS_RESULT = {
    "data": [
        {
            "hostGroupNumber": 0,
            "iscsiName": CONFIG_MAP['host_iscsi_name'],
        },
    ],
}

GET_HOST_GROUP_RESULT = {
    "hostGroupName": CONFIG_MAP['host_grp_name'],
    "iscsiName": CONFIG_MAP['target_iscsi_name'],
}

GET_HOST_GROUPS_RESULT = {
    "data": [
        {
            "hostGroupNumber": 0,
            "portId": CONFIG_MAP['port_id'],
            "hostGroupName": "NEC-test",
            "iscsiName": CONFIG_MAP['target_iscsi_name'],
        },
    ],
}

COMPLETED_SUCCEEDED_RESULT = {
    "status": "Completed",
    "state": "Succeeded",
    "affectedResources": ('a/b/c/1',),
}


def _brick_get_connector_properties(multipath=False, enforce_multipath=False):
    """Return a predefined connector object."""
    return DEFAULT_CONNECTOR


class FakeResponse():

    def __init__(self, status_code, data=None, headers=None):
        self.status_code = status_code
        self.data = data
        self.text = data
        self.content = data
        self.headers = {'Content-Type': 'json'} if headers is None else headers

    def json(self):
        return self.data


class VStorageRESTISCSIDriverTest(test.TestCase):
    """Unit test class for NEC REST interface iSCSI module."""

    test_existing_ref = {'source-id': '1'}
    test_existing_ref_name = {
        'source-name': '15960cc7-38c9-4c5b-b4f1-365be5eeed45'}

    def setUp(self):
        """Set up the test environment."""
        def _set_required(opts, required):
            for opt in opts:
                opt.required = required

        # Initialize Cinder and avoid checking driver options.
        rest_required_opts = [
            opt for opt in nec_v_rest.REST_VOLUME_OPTS if opt.required]
        common_required_opts = [
            opt for opt in nec_v_rest.COMMON_VOLUME_OPTS if opt.required]
        _set_required(rest_required_opts, False)
        _set_required(common_required_opts, False)
        super(VStorageRESTISCSIDriverTest, self).setUp()
        _set_required(rest_required_opts, True)
        _set_required(common_required_opts, True)

        self.configuration = mock.Mock(conf.Configuration)
        self.ctxt = cinder_context.get_admin_context()
        self._setup_config()
        self._setup_driver()

    def _setup_config(self):
        """Set configuration parameter values."""
        self.configuration.config_group = "REST"

        self.configuration.volume_backend_name = "RESTISCSI"
        self.configuration.volume_driver = (
            "cinder.volume.drivers.nec.v.nec_v_iscsi.VStorageISCSIDriver")
        self.configuration.reserved_percentage = "0"
        self.configuration.use_multipath_for_image_xfer = False
        self.configuration.enforce_multipath_for_image_xfer = False
        self.configuration.max_over_subscription_ratio = 500.0
        self.configuration.driver_ssl_cert_verify = False

        self.configuration.nec_v_storage_id = CONFIG_MAP['serial']
        self.configuration.nec_v_pool = "30"
        self.configuration.nec_v_snap_pool = None
        self.configuration.nec_v_ldev_range = "0-1"
        self.configuration.nec_v_target_ports = [CONFIG_MAP['port_id']]
        self.configuration.nec_v_compute_target_ports = [
            CONFIG_MAP['port_id']]
        self.configuration.nec_v_group_create = True
        self.configuration.nec_v_group_delete = True
        self.configuration.nec_v_copy_speed = 3
        self.configuration.nec_v_copy_check_interval = 3
        self.configuration.nec_v_async_copy_check_interval = 10

        self.configuration.san_login = CONFIG_MAP['user_id']
        self.configuration.san_password = CONFIG_MAP['user_pass']
        self.configuration.san_ip = CONFIG_MAP[
            'rest_server_ip_addr']
        self.configuration.san_api_port = CONFIG_MAP[
            'rest_server_ip_port']
        self.configuration.nec_v_rest_disable_io_wait = True
        self.configuration.nec_v_rest_tcp_keepalive = True
        self.configuration.nec_v_discard_zero_page = True
        self.configuration.nec_v_rest_number = "0"
        self.configuration.nec_v_lun_timeout = hbsd_rest._LUN_TIMEOUT
        self.configuration.nec_v_lun_retry_interval = (
            hbsd_rest._LUN_RETRY_INTERVAL)
        self.configuration.nec_v_restore_timeout = hbsd_rest._RESTORE_TIMEOUT
        self.configuration.nec_v_state_transition_timeout = (
            hbsd_rest._STATE_TRANSITION_TIMEOUT)
        self.configuration.nec_v_lock_timeout = hbsd_rest_api._LOCK_TIMEOUT
        self.configuration.nec_v_rest_timeout = hbsd_rest_api._REST_TIMEOUT
        self.configuration.nec_v_extend_timeout = (
            hbsd_rest_api._EXTEND_TIMEOUT)
        self.configuration.nec_v_exec_retry_interval = (
            hbsd_rest_api._EXEC_RETRY_INTERVAL)
        self.configuration.nec_v_rest_connect_timeout = (
            hbsd_rest_api._DEFAULT_CONNECT_TIMEOUT)
        self.configuration.nec_v_rest_job_api_response_timeout = (
            hbsd_rest_api._JOB_API_RESPONSE_TIMEOUT)
        self.configuration.nec_v_rest_get_api_response_timeout = (
            hbsd_rest_api._GET_API_RESPONSE_TIMEOUT)
        self.configuration.nec_v_rest_server_busy_timeout = (
            hbsd_rest_api._REST_SERVER_BUSY_TIMEOUT)
        self.configuration.nec_v_rest_keep_session_loop_interval = (
            hbsd_rest_api._KEEP_SESSION_LOOP_INTERVAL)
        self.configuration.nec_v_rest_another_ldev_mapped_retry_timeout = (
            hbsd_rest_api._ANOTHER_LDEV_MAPPED_RETRY_TIMEOUT)
        self.configuration.nec_v_rest_tcp_keepidle = (
            hbsd_rest_api._TCP_KEEPIDLE)
        self.configuration.nec_v_rest_tcp_keepintvl = (
            hbsd_rest_api._TCP_KEEPINTVL)
        self.configuration.nec_v_rest_tcp_keepcnt = (
            hbsd_rest_api._TCP_KEEPCNT)
        self.configuration.nec_v_host_mode_options = []

        self.configuration.use_chap_auth = True
        self.configuration.chap_username = CONFIG_MAP['auth_user']
        self.configuration.chap_password = CONFIG_MAP['auth_password']

        self.configuration.san_thin_provision = True
        self.configuration.san_private_key = ''
        self.configuration.san_clustername = ''
        self.configuration.san_ssh_port = '22'
        self.configuration.san_is_local = False
        self.configuration.ssh_conn_timeout = '30'
        self.configuration.ssh_min_pool_conn = '1'
        self.configuration.ssh_max_pool_conn = '5'

        self.configuration.safe_get = self._fake_safe_get

        CONF = cfg.CONF
        CONF.my_ip = CONFIG_MAP['my_ip']

    def _fake_safe_get(self, value):
        """Retrieve a configuration value avoiding throwing an exception."""
        try:
            val = getattr(self.configuration, value)
        except AttributeError:
            val = None
        return val

    @mock.patch.object(requests.Session, "request")
    @mock.patch.object(
        volume_utils, 'brick_get_connector_properties',
        side_effect=_brick_get_connector_properties)
    def _setup_driver(
            self, brick_get_connector_properties=None, request=None):
        """Set up the driver environment."""
        self.driver = nec_v_iscsi.VStorageISCSIDriver(
            configuration=self.configuration, db=db)
        request.side_effect = [FakeResponse(200, POST_SESSIONS_RESULT),
                               FakeResponse(200, GET_PORTS_RESULT),
                               FakeResponse(200, GET_PORT_RESULT),
                               FakeResponse(200, GET_HOST_ISCSIS_RESULT),
                               FakeResponse(200, GET_HOST_GROUP_RESULT)]
        self.driver.do_setup(None)
        self.driver.check_for_setup_error()
        self.driver.local_path(None)
        # stop the Loopingcall within the do_setup treatment
        self.driver.common.client.keep_session_loop.stop()

    def tearDown(self):
        self.client = None
        super(VStorageRESTISCSIDriverTest, self).tearDown()

    # API test cases
    def test_configuration(self):
        drv = nec_v_iscsi.VStorageISCSIDriver(
            configuration=self.configuration, db=db)
        self.assertEqual(drv.configuration.hitachi_storage_id,
                         drv.configuration.nec_v_storage_id)
        self.assertEqual(drv.configuration.hitachi_pool,
                         drv.configuration.nec_v_pool)
        self.assertEqual(drv.configuration.hitachi_snap_pool,
                         drv.configuration.nec_v_snap_pool)
        self.assertEqual(drv.configuration.hitachi_ldev_range,
                         drv.configuration.nec_v_ldev_range)
        self.assertEqual(drv.configuration.hitachi_target_ports,
                         drv.configuration.nec_v_target_ports)
        self.assertEqual(drv.configuration.hitachi_compute_target_ports,
                         drv.configuration.nec_v_compute_target_ports)
        self.assertEqual(drv.configuration.hitachi_group_create,
                         drv.configuration.nec_v_group_create)
        self.assertEqual(drv.configuration.hitachi_group_delete,
                         drv.configuration.nec_v_group_delete)
        self.assertEqual(drv.configuration.hitachi_copy_speed,
                         drv.configuration.nec_v_copy_speed)
        self.assertEqual(drv.configuration.hitachi_copy_check_interval,
                         drv.configuration.nec_v_copy_check_interval)
        self.assertEqual(drv.configuration.hitachi_async_copy_check_interval,
                         drv.configuration.nec_v_async_copy_check_interval)
        self.assertEqual(drv.configuration.hitachi_rest_disable_io_wait,
                         drv.configuration.nec_v_rest_disable_io_wait)
        self.assertEqual(drv.configuration.hitachi_rest_tcp_keepalive,
                         drv.configuration.nec_v_rest_tcp_keepalive)
        self.assertEqual(drv.configuration.hitachi_discard_zero_page,
                         drv.configuration.nec_v_discard_zero_page)
        self.assertEqual(drv.configuration.hitachi_lun_timeout,
                         drv.configuration.nec_v_lun_timeout)
        self.assertEqual(drv.configuration.hitachi_lun_retry_interval,
                         drv.configuration.nec_v_lun_retry_interval)
        self.assertEqual(drv.configuration.hitachi_restore_timeout,
                         drv.configuration.nec_v_restore_timeout)
        self.assertEqual(drv.configuration.hitachi_state_transition_timeout,
                         drv.configuration.nec_v_state_transition_timeout)
        self.assertEqual(drv.configuration.hitachi_lock_timeout,
                         drv.configuration.nec_v_lock_timeout)
        self.assertEqual(drv.configuration.hitachi_rest_timeout,
                         drv.configuration.nec_v_rest_timeout)
        self.assertEqual(drv.configuration.hitachi_extend_timeout,
                         drv.configuration.nec_v_extend_timeout)
        self.assertEqual(drv.configuration.hitachi_exec_retry_interval,
                         drv.configuration.nec_v_exec_retry_interval)
        self.assertEqual(drv.configuration.hitachi_rest_connect_timeout,
                         drv.configuration.nec_v_rest_connect_timeout)
        self.assertEqual(
            drv.configuration.hitachi_rest_job_api_response_timeout,
            drv.configuration.nec_v_rest_job_api_response_timeout)
        self.assertEqual(
            drv.configuration.hitachi_rest_get_api_response_timeout,
            drv.configuration.nec_v_rest_get_api_response_timeout)
        self.assertEqual(drv.configuration.hitachi_rest_server_busy_timeout,
                         drv.configuration.nec_v_rest_server_busy_timeout)
        self.assertEqual(
            drv.configuration.hitachi_rest_keep_session_loop_interval,
            drv.configuration.nec_v_rest_keep_session_loop_interval)
        self.assertEqual(
            drv.configuration.hitachi_rest_another_ldev_mapped_retry_timeout,
            drv.configuration.nec_v_rest_another_ldev_mapped_retry_timeout)
        self.assertEqual(drv.configuration.hitachi_rest_tcp_keepidle,
                         drv.configuration.nec_v_rest_tcp_keepidle)
        self.assertEqual(drv.configuration.hitachi_rest_tcp_keepintvl,
                         drv.configuration.nec_v_rest_tcp_keepintvl)
        self.assertEqual(drv.configuration.hitachi_rest_tcp_keepcnt,
                         drv.configuration.nec_v_rest_tcp_keepcnt)
        self.assertEqual(drv.configuration.hitachi_host_mode_options,
                         drv.configuration.nec_v_host_mode_options)

    def test_driverinfo(self):
        drv = nec_v_iscsi.VStorageISCSIDriver(
            configuration=self.configuration, db=db)
        self.assertEqual(drv.common.driver_info['version'],
                         "1.0.0")
        self.assertEqual(drv.common.driver_info['proto'],
                         "iSCSI")
        self.assertEqual(drv.common.driver_info['hba_id'],
                         "initiator")
        self.assertEqual(drv.common.driver_info['hba_id_type'],
                         "iSCSI initiator IQN")
        self.assertEqual(drv.common.driver_info['msg_id']['target'].msg_id,
                         309)
        self.assertEqual(drv.common.driver_info['volume_backend_name'],
                         "NECiSCSI")
        self.assertEqual(drv.common.driver_info['volume_type'],
                         "iscsi")
        self.assertEqual(drv.common.driver_info['param_prefix'],
                         "nec_v")
        self.assertEqual(drv.common.driver_info['vendor_name'],
                         "NEC")
        self.assertEqual(drv.common.driver_info['driver_prefix'],
                         "NEC")
        self.assertEqual(drv.common.driver_info['driver_file_prefix'],
                         "nec")
        self.assertEqual(drv.common.driver_info['target_prefix'],
                         "NEC-")
        self.assertEqual(drv.common.driver_info['hdp_vol_attr'],
                         "DP")
        self.assertEqual(drv.common.driver_info['hdt_vol_attr'],
                         "DT")
        self.assertEqual(drv.common.driver_info['nvol_ldev_type'],
                         "DP-VOL")
        self.assertEqual(drv.common.driver_info['target_iqn_suffix'],
                         ".nec-target")
        self.assertEqual(drv.common.driver_info['pair_attr'],
                         "SS")

    @mock.patch.object(requests.Session, "request")
    def test_create_volume(self, request):
        request.return_value = FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)
        ret = self.driver.create_volume(fake_volume.fake_volume_obj(self.ctxt))
        self.assertEqual('1', ret['provider_location'])
        self.assertEqual(2, request.call_count)
