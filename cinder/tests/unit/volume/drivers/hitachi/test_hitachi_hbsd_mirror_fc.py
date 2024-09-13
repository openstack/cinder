# Copyright (C) 2022, 2024, Hitachi, Ltd.
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
"""Unit tests for Hitachi HBSD Driver."""

import json
from unittest import mock

from oslo_config import cfg
import requests

from cinder import context as cinder_context
from cinder.db.sqlalchemy import api as sqlalchemy_api
from cinder import exception
from cinder.objects import group_snapshot as obj_group_snap
from cinder.objects import snapshot as obj_snap
from cinder.tests.unit import fake_group
from cinder.tests.unit import fake_group_snapshot
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit import test
from cinder.volume import configuration as conf
from cinder.volume import driver
from cinder.volume.drivers.hitachi import hbsd_common
from cinder.volume.drivers.hitachi import hbsd_fc
from cinder.volume.drivers.hitachi import hbsd_rest
from cinder.volume.drivers.hitachi import hbsd_rest_api
from cinder.volume.drivers.hitachi import hbsd_utils
from cinder.volume import volume_types
from cinder.volume import volume_utils
from cinder.zonemanager import utils as fczm_utils

# Configuration parameter values
CONFIG_MAP = {
    'serial': '886000123456',
    'my_ip': '127.0.0.1',
    'rest_server_ip_addr': '172.16.18.108',
    'rest_server_ip_port': '23451',
    'port_id': 'CL1-A',
    'host_grp_name': 'HBSD-0123456789abcdef',
    'host_mode': 'LINUX/IRIX',
    'host_wwn': '0123456789abcdef',
    'target_wwn': '1111111123456789',
    'user_id': 'user',
    'user_pass': 'password',
    'pool_name': 'test_pool',
    'auth_user': 'auth_user',
    'auth_password': 'auth_password',
}

REMOTE_CONFIG_MAP = {
    'serial': '886000456789',
    'my_ip': '127.0.0.1',
    'rest_server_ip_addr': '172.16.18.107',
    'rest_server_ip_port': '334',
    'port_id': 'CL2-B',
    'host_grp_name': 'HBSD-0123456789abcdef',
    'host_mode': 'LINUX/IRIX',
    'host_wwn': '0123456789abcdef',
    'target_wwn': '2222222234567891',
    'user_id': 'remote-user',
    'user_pass': 'remote-password',
    'pool_name': 'remote_pool',
    'auth_user': 'remote_user',
    'auth_password': 'remote_password',
}

# Dummy response for FC zoning device mapping
DEVICE_MAP = {
    'fabric_name': {
        'initiator_port_wwn_list': [CONFIG_MAP['host_wwn']],
        'target_port_wwn_list': [CONFIG_MAP['target_wwn']]}}

REMOTE_DEVICE_MAP = {
    'fabric_name': {
        'initiator_port_wwn_list': [REMOTE_CONFIG_MAP['host_wwn']],
        'target_port_wwn_list': [REMOTE_CONFIG_MAP['target_wwn']]}}

DEFAULT_CONNECTOR = {
    'host': 'host',
    'ip': CONFIG_MAP['my_ip'],
    'wwpns': [CONFIG_MAP['host_wwn']],
    'multipath': False,
}

REMOTE_DEFAULT_CONNECTOR = {
    'host': 'host',
    'ip': REMOTE_CONFIG_MAP['my_ip'],
    'wwpns': [REMOTE_CONFIG_MAP['host_wwn']],
    'multipath': False,
}

CTXT = cinder_context.get_admin_context()

TEST_VOLUME = []
for i in range(8):
    volume = {}
    volume['id'] = '00000000-0000-0000-0000-{0:012d}'.format(i)
    volume['name'] = 'test-volume{0:d}'.format(i)
    volume['volume_type_id'] = '00000000-0000-0000-0000-{0:012d}'.format(i)
    if i == 3 or i == 7:
        volume['provider_location'] = None
    elif i == 4:
        volume['provider_location'] = json.dumps(
            {'pldev': 4, 'sldev': 4,
             'remote-copy': hbsd_utils.MIRROR_ATTR})
    elif i == 5:
        volume['provider_location'] = json.dumps(
            {'pldev': 5, 'sldev': 5,
             'remote-copy': hbsd_utils.MIRROR_ATTR})
    elif i == 6:
        volume['provider_location'] = json.dumps(
            {'pldev': 6, 'sldev': 6,
             'remote-copy': hbsd_utils.MIRROR_ATTR})
    else:
        volume['provider_location'] = '{0:d}'.format(i)
    volume['size'] = 128
    if i == 2 or i == 6:
        volume['status'] = 'in-use'
    elif i == 7:
        volume['status'] = None
    else:
        volume['status'] = 'available'
    volume = fake_volume.fake_volume_obj(CTXT, **volume)
    volume.volume_type = fake_volume.fake_volume_type_obj(CTXT)
    TEST_VOLUME.append(volume)


def _volume_get(context, volume_id):
    """Return predefined volume info."""
    return TEST_VOLUME[int(volume_id.replace("-", ""))]


TEST_SNAPSHOT = []
for i in range(2):
    snapshot = {}
    snapshot['id'] = '10000000-0000-0000-0000-{0:012d}'.format(i)
    snapshot['name'] = 'TEST_SNAPSHOT{0:d}'.format(i)
    snapshot['provider_location'] = '{0:d}'.format(i + 1)
    snapshot['status'] = 'available'
    snapshot['volume_id'] = '00000000-0000-0000-0000-{0:012d}'.format(i)
    snapshot['volume'] = _volume_get(None, snapshot['volume_id'])
    snapshot['volume_name'] = 'test-volume{0:d}'.format(i)
    snapshot['volume_size'] = 128
    snapshot = obj_snap.Snapshot._from_db_object(
        CTXT, obj_snap.Snapshot(),
        fake_snapshot.fake_db_snapshot(**snapshot))
    TEST_SNAPSHOT.append(snapshot)

TEST_GROUP = []
for i in range(2):
    group = {}
    group['id'] = '20000000-0000-0000-0000-{0:012d}'.format(i)
    group['status'] = 'available'
    group = fake_group.fake_group_obj(CTXT, **group)
    TEST_GROUP.append(group)

TEST_GROUP_SNAP = []
group_snapshot = {}
group_snapshot['id'] = '30000000-0000-0000-0000-{0:012d}'.format(0)
group_snapshot['status'] = 'available'
group_snapshot = obj_group_snap.GroupSnapshot._from_db_object(
    CTXT, obj_group_snap.GroupSnapshot(),
    fake_group_snapshot.fake_db_group_snapshot(**group_snapshot))
TEST_GROUP_SNAP.append(group_snapshot)

# Dummy response for REST API
POST_SESSIONS_RESULT = {
    "token": "b74777a3-f9f0-4ea8-bd8f-09847fac48d3",
    "sessionId": 0,
}

REMOTE_POST_SESSIONS_RESULT = {
    "token": "b74777a3-f9f0-4ea8-bd8f-09847fac48d4",
    "sessionId": 0,
}

GET_PORTS_RESULT = {
    "data": [
        {
            "portId": CONFIG_MAP['port_id'],
            "portType": "FIBRE",
            "portAttributes": [
                "TAR",
                "MCU",
                "RCU",
                "ELUN"
            ],
            "fabricMode": True,
            "portConnection": "PtoP",
            "lunSecuritySetting": True,
            "wwn": CONFIG_MAP['target_wwn'],
        },
    ],
}

REMOTE_GET_PORTS_RESULT = {
    "data": [
        {
            "portId": REMOTE_CONFIG_MAP['port_id'],
            "portType": "FIBRE",
            "portAttributes": [
                "TAR",
                "MCU",
                "RCU",
                "ELUN"
            ],
            "fabricMode": True,
            "portConnection": "PtoP",
            "lunSecuritySetting": True,
            "wwn": REMOTE_CONFIG_MAP['target_wwn'],
        },
    ],
}

GET_HOST_WWNS_RESULT = {
    "data": [
        {
            "hostGroupNumber": 0,
            "hostWwn": CONFIG_MAP['host_wwn'],
        },
    ],
}

REMOTE_GET_HOST_WWNS_RESULT = {
    "data": [
        {
            "hostGroupNumber": 0,
            "hostWwn": REMOTE_CONFIG_MAP['host_wwn'],
        },
    ],
}

COMPLETED_SUCCEEDED_RESULT = {
    "status": "Completed",
    "state": "Succeeded",
    "affectedResources": ('a/b/c/1',),
}

REMOTE_COMPLETED_SUCCEEDED_RESULT = {
    "status": "Completed",
    "state": "Succeeded",
    "affectedResources": ('a/b/c/2',),
}

COMPLETED_FAILED_RESULT_LU_DEFINED = {
    "status": "Completed",
    "state": "Failed",
    "error": {
        "errorCode": {
            "SSB1": "B958",
            "SSB2": "015A",
        },
    },
}

GET_LDEV_RESULT = {
    "emulationType": "OPEN-V-CVS",
    "blockCapacity": 2097152,
    "attributes": ["CVS", "HDP"],
    "status": "NML",
    "poolId": 30,
    "dataReductionStatus": "DISABLED",
    "dataReductionMode": "disabled",
    "label": "00000000000000000000000000000000",
}

GET_LDEV_RESULT_SPLIT = {
    "emulationType": "OPEN-V-CVS",
    "blockCapacity": 2097152,
    "attributes": ["CVS", "HDP"],
    "status": "NML",
    "poolId": 30,
    "dataReductionStatus": "DISABLED",
    "dataReductionMode": "disabled",
    "label": "00000000000000000000000000000004",
}

GET_LDEV_RESULT_LABEL = {
    "emulationType": "OPEN-V-CVS",
    "blockCapacity": 2097152,
    "attributes": ["CVS", "HDP"],
    "status": "NML",
    "poolId": 30,
    "dataReductionStatus": "DISABLED",
    "dataReductionMode": "disabled",
    "label": "00000000000000000000000000000001",
}

GET_LDEV_RESULT_MAPPED = {
    "emulationType": "OPEN-V-CVS",
    "blockCapacity": 2097152,
    "attributes": ["CVS", "HDP"],
    "status": "NML",
    "ports": [
        {
            "portId": CONFIG_MAP['port_id'],
            "hostGroupNumber": 0,
            "hostGroupName": CONFIG_MAP['host_grp_name'],
            "lun": 1
        },
    ],
}

REMOTE_GET_LDEV_RESULT_MAPPED = {
    "emulationType": "OPEN-V-CVS",
    "blockCapacity": 2097152,
    "attributes": ["CVS", "HDP"],
    "status": "NML",
    "ports": [
        {
            "portId": REMOTE_CONFIG_MAP['port_id'],
            "hostGroupNumber": 0,
            "hostGroupName": REMOTE_CONFIG_MAP['host_grp_name'],
            "lun": 1
        },
    ],
}

GET_LDEV_RESULT_PAIR = {
    "emulationType": "OPEN-V-CVS",
    "blockCapacity": 2097152,
    "attributes": ["CVS", "HDP", "HTI"],
    "status": "NML",
    "label": "10000000000000000000000000000000",
}

GET_LDEV_RESULT_REP = {
    "emulationType": "OPEN-V-CVS",
    "blockCapacity": 2097152,
    "attributes": ["CVS", "HDP", "GAD"],
    "status": "NML",
    "numOfPorts": 1,
    "label": "00000000000000000000000000000004",
}

GET_LDEV_RESULT_REP_LABEL = {
    "emulationType": "OPEN-V-CVS",
    "blockCapacity": 2097152,
    "attributes": ["CVS", "HDP", "GAD"],
    "status": "NML",
    "numOfPorts": 1,
    "label": "00000000000000000000000000000001",
}

GET_POOL_RESULT = {
    "availableVolumeCapacity": 480144,
    "totalPoolCapacity": 507780,
    "totalLocatedCapacity": 71453172,
    "virtualVolumeCapacityRate": -1,
}

GET_POOLS_RESULT = {
    "data": [
        {
            "poolId": 30,
            "poolName": CONFIG_MAP['pool_name'],
            "availableVolumeCapacity": 480144,
            "totalPoolCapacity": 507780,
            "totalLocatedCapacity": 71453172,
            "virtualVolumeCapacityRate": -1,
        },
    ],
}

GET_SNAPSHOTS_RESULT = {
    "data": [
        {
            "primaryOrSecondary": "S-VOL",
            "status": "PSUS",
            "pvolLdevId": 0,
            "muNumber": 1,
            "svolLdevId": 1,
        },
    ],
}

GET_SNAPSHOTS_RESULT_PAIR = {
    "data": [
        {
            "primaryOrSecondary": "S-VOL",
            "status": "PAIR",
            "pvolLdevId": 0,
            "muNumber": 1,
            "svolLdevId": 1,
        },
    ],
}

GET_SNAPSHOTS_RESULT_BUSY = {
    "data": [
        {
            "primaryOrSecondary": "P-VOL",
            "status": "PSUP",
            "pvolLdevId": 0,
            "muNumber": 1,
            "svolLdevId": 1,
        },
    ],
}

GET_SNAPSHOTS_RESULT_TEST = {
    "data": [
        {
            "primaryOrSecondary": "S-VOL",
            "status": "PSUS",
            "pvolLdevId": 1,
            "muNumber": 1,
            "svolLdevId": 1,
        },
    ],
}

GET_LUNS_RESULT = {
    "data": [
        {
            "ldevId": 0,
            "lun": 1,
        },
    ],
}

GET_HOST_GROUP_RESULT = {
    "hostGroupName": CONFIG_MAP['host_grp_name'],
}

GET_HOST_GROUPS_RESULT = {
    "data": [
        {
            "hostGroupNumber": 0,
            "portId": CONFIG_MAP['port_id'],
            "hostGroupName": "HBSD-test",
        },
    ],
}

GET_HOST_GROUPS_RESULT_PAIR = {
    "data": [
        {
            "hostGroupNumber": 1,
            "portId": CONFIG_MAP['port_id'],
            "hostGroupName": "HBSD-pair00",
        },
    ],
}

REMOTE_GET_HOST_GROUPS_RESULT_PAIR = {
    "data": [
        {
            "hostGroupNumber": 1,
            "portId": REMOTE_CONFIG_MAP['port_id'],
            "hostGroupName": "HBSD-pair00",
        },
    ],
}

GET_LDEVS_RESULT = {
    "data": [
        {
            "ldevId": 0,
            "label": "15960cc738c94c5bb4f1365be5eeed44",
        },
        {
            "ldevId": 1,
            "label": "15960cc738c94c5bb4f1365be5eeed45",
        },
    ],
}

GET_REMOTE_MIRROR_COPYPAIR_RESULT = {
    'pvolLdevId': 4,
    'svolLdevId': 4,
    'pvolStatus': 'PAIR',
    'svolStatus': 'PAIR',
    'replicationType': hbsd_utils.MIRROR_ATTR,
}

GET_REMOTE_MIRROR_COPYPAIR_RESULT_SPLIT = {
    'pvolLdevId': 4,
    'svolLdevId': 4,
    'pvolStatus': 'PSUS',
    'svolStatus': 'SSUS',
    'replicationType': hbsd_utils.MIRROR_ATTR,
}

GET_REMOTE_MIRROR_COPYGROUP_RESULT = {
    'copyGroupName': 'HBSD-127.0.0.100U00',
    'copyPairs': [GET_REMOTE_MIRROR_COPYPAIR_RESULT],
}

GET_REMOTE_MIRROR_COPYGROUP_RESULT_ERROR = {
    "errorSource": "<URL>",
    "message": "<message>",
    "solution": "<solution>",
    "messageId": "aaa",
    "errorCode": {
                   "SSB1": "",
                   "SSB2": "",
    }
}

NOTFOUND_RESULT = {
    "data": [],
}

ERROR_RESULT = {
    "errorSource": "<URL>",
    "message": "<message>",
    "solution": "<solution>",
    "messageId": "<messageId>",
    "errorCode": {
                   "SSB1": "",
                   "SSB2": "",
    }
}


def _brick_get_connector_properties(multipath=False, enforce_multipath=False):
    """Return a predefined connector object."""
    return DEFAULT_CONNECTOR


class FakeLookupService():
    """Dummy FC zoning mapping lookup service class."""

    def get_device_mapping_from_network(self, initiator_wwns, target_wwns):
        """Return predefined FC zoning mapping."""
        return DEVICE_MAP


class FakeResponse():

    def __init__(self, status_code, data=None, headers=None):
        self.status_code = status_code
        self.data = data
        self.text = data
        self.content = data
        self.headers = {'Content-Type': 'json'} if headers is None else headers

    def json(self):
        return self.data


class HBSDMIRRORFCDriverTest(test.TestCase):
    """Unit test class for HBSD MIRROR interface fibre channel module."""

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
            opt for opt in hbsd_rest.REST_VOLUME_OPTS if opt.required]
        common_required_opts = [
            opt for opt in hbsd_common.COMMON_VOLUME_OPTS if opt.required]
        _set_required(rest_required_opts, False)
        _set_required(common_required_opts, False)
        super(HBSDMIRRORFCDriverTest, self).setUp()
        _set_required(rest_required_opts, True)
        _set_required(common_required_opts, True)

        self.configuration = conf.Configuration(None)
        self.ctxt = cinder_context.get_admin_context()
        self._setup_config()
        self._setup_driver()

    def _setup_config(self):
        """Set configuration parameter values."""
        self.configuration.config_group = "REST"

        self.configuration.volume_backend_name = "RESTFC"
        self.configuration.volume_driver = (
            "cinder.volume.drivers.hitachi.hbsd_fc.HBSDFCDriver")
        self.configuration.reserved_percentage = "0"
        self.configuration.use_multipath_for_image_xfer = False
        self.configuration.enforce_multipath_for_image_xfer = False
        self.configuration.max_over_subscription_ratio = 500.0
        self.configuration.driver_ssl_cert_verify = False

        self.configuration.hitachi_storage_id = CONFIG_MAP['serial']
        self.configuration.hitachi_pools = ["30"]
        self.configuration.hitachi_snap_pool = None
        self.configuration.hitachi_ldev_range = "0-1"
        self.configuration.hitachi_target_ports = [CONFIG_MAP['port_id']]
        self.configuration.hitachi_compute_target_ports\
            = [CONFIG_MAP['port_id']]
        self.configuration.hitachi_group_create = True
        self.configuration.hitachi_group_delete = True
        self.configuration.hitachi_copy_speed = 3
        self.configuration.hitachi_copy_check_interval = 3
        self.configuration.hitachi_async_copy_check_interval = 10

        self.configuration.san_login = CONFIG_MAP['user_id']
        self.configuration.san_password = CONFIG_MAP['user_pass']
        self.configuration.san_ip = CONFIG_MAP[
            'rest_server_ip_addr']
        self.configuration.san_api_port = CONFIG_MAP[
            'rest_server_ip_port']
        self.configuration.hitachi_rest_disable_io_wait = True
        self.configuration.hitachi_rest_tcp_keepalive = True
        self.configuration.hitachi_discard_zero_page = True
        self.configuration.hitachi_lun_timeout = hbsd_rest._LUN_TIMEOUT
        self.configuration.hitachi_lun_retry_interval = (
            hbsd_rest._LUN_RETRY_INTERVAL)
        self.configuration.hitachi_restore_timeout = hbsd_rest._RESTORE_TIMEOUT
        self.configuration.hitachi_state_transition_timeout = (
            hbsd_rest._STATE_TRANSITION_TIMEOUT)
        self.configuration.hitachi_lock_timeout = hbsd_rest_api._LOCK_TIMEOUT
        self.configuration.hitachi_rest_timeout = hbsd_rest_api._REST_TIMEOUT
        self.configuration.hitachi_extend_timeout = (
            hbsd_rest_api._EXTEND_TIMEOUT)
        self.configuration.hitachi_exec_retry_interval = (
            hbsd_rest_api._EXEC_RETRY_INTERVAL)
        self.configuration.hitachi_rest_connect_timeout = (
            hbsd_rest_api._DEFAULT_CONNECT_TIMEOUT)
        self.configuration.hitachi_rest_job_api_response_timeout = (
            hbsd_rest_api._JOB_API_RESPONSE_TIMEOUT)
        self.configuration.hitachi_rest_get_api_response_timeout = (
            hbsd_rest_api._GET_API_RESPONSE_TIMEOUT)
        self.configuration.hitachi_rest_server_busy_timeout = (
            hbsd_rest_api._REST_SERVER_BUSY_TIMEOUT)
        self.configuration.hitachi_rest_keep_session_loop_interval = (
            hbsd_rest_api._KEEP_SESSION_LOOP_INTERVAL)
        self.configuration.hitachi_rest_another_ldev_mapped_retry_timeout = (
            hbsd_rest_api._ANOTHER_LDEV_MAPPED_RETRY_TIMEOUT)
        self.configuration.hitachi_rest_tcp_keepidle = (
            hbsd_rest_api._TCP_KEEPIDLE)
        self.configuration.hitachi_rest_tcp_keepintvl = (
            hbsd_rest_api._TCP_KEEPINTVL)
        self.configuration.hitachi_rest_tcp_keepcnt = (
            hbsd_rest_api._TCP_KEEPCNT)
        self.configuration.hitachi_host_mode_options = []

        self.configuration.hitachi_zoning_request = False

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

        self.configuration.hitachi_replication_status_check_short_interval = 5
        self.configuration.hitachi_replication_status_check_long_interval\
            = 10 * 60
        self.configuration.hitachi_replication_status_check_timeout\
            = 24 * 60 * 60

        self.configuration.hitachi_replication_number = 0
        self.configuration.hitachi_pair_target_number = 0
        self.configuration.hitachi_rest_pair_target_ports\
            = [CONFIG_MAP['port_id']]
        self.configuration.hitachi_quorum_disk_id = 13
        self.configuration.hitachi_mirror_copy_speed = 3
        self.configuration.hitachi_mirror_storage_id\
            = REMOTE_CONFIG_MAP['serial']
        self.configuration.hitachi_mirror_pool = '40'
        self.configuration.hitachi_mirror_snap_pool = None
        self.configuration.hitachi_mirror_ldev_range = '2-3'
        self.configuration.hitachi_mirror_target_ports\
            = [REMOTE_CONFIG_MAP['port_id']]
        self.configuration.hitachi_mirror_compute_target_ports\
            = [REMOTE_CONFIG_MAP['port_id']]
        self.configuration.hitachi_mirror_pair_target_number = 0
        self.configuration.hitachi_mirror_rest_pair_target_ports\
            = [REMOTE_CONFIG_MAP['port_id']]
        self.configuration.hitachi_mirror_rest_user\
            = REMOTE_CONFIG_MAP['user_id']
        self.configuration.hitachi_mirror_rest_password\
            = REMOTE_CONFIG_MAP['user_pass']
        self.configuration.hitachi_mirror_rest_api_ip\
            = REMOTE_CONFIG_MAP['rest_server_ip_addr']
        self.configuration.hitachi_mirror_rest_api_port\
            = REMOTE_CONFIG_MAP['rest_server_ip_port']
        self.configuration.hitachi_set_mirror_reserve_attribute = True
        self.configuration.hitachi_path_group_id = 0

        self.configuration.hitachi_mirror_use_chap_auth = True
        self.configuration.hitachi_mirror_chap_user = CONFIG_MAP['auth_user']
        self.configuration.hitachi_mirror_chap_password\
            = CONFIG_MAP['auth_password']

        self.configuration.hitachi_mirror_ssl_cert_verify = False
        self.configuration.hitachi_mirror_ssl_cert_path = '/root/path'

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
        self.driver = hbsd_fc.HBSDFCDriver(
            configuration=self.configuration)

        def _request_side_effect(
                method, url, params, json, headers, auth, timeout, verify):
            if self.configuration.hitachi_storage_id in url:
                if method == 'POST':
                    return FakeResponse(200, POST_SESSIONS_RESULT)
                elif '/ports' in url:
                    return FakeResponse(200, GET_PORTS_RESULT)
                elif '/host-wwns' in url:
                    return FakeResponse(200, GET_HOST_WWNS_RESULT)
                elif '/host-groups' in url:
                    return FakeResponse(200, GET_HOST_GROUPS_RESULT_PAIR)
            else:
                if method == 'POST':
                    return FakeResponse(200, REMOTE_POST_SESSIONS_RESULT)
                elif '/ports' in url:
                    return FakeResponse(200, REMOTE_GET_PORTS_RESULT)
                elif '/host-wwns' in url:
                    return FakeResponse(200, REMOTE_GET_HOST_WWNS_RESULT)
                elif '/host-groups' in url:
                    return FakeResponse(
                        200, REMOTE_GET_HOST_GROUPS_RESULT_PAIR)
            return FakeResponse(
                500, ERROR_RESULT, headers={'Content-Type': 'json'})
        request.side_effect = _request_side_effect
        self.driver.do_setup(None)
        self.driver.check_for_setup_error()
        self.driver.local_path(None)
        self.driver.create_export(None, None, None)
        self.driver.ensure_export(None, None)
        self.driver.remove_export(None, None)
        self.driver.create_export_snapshot(None, None, None)
        self.driver.remove_export_snapshot(None, None)
        # stop the Loopingcall within the do_setup treatment
        self.driver.common.rep_primary.client.keep_session_loop.stop()
        self.driver.common.rep_secondary.client.keep_session_loop.stop()

    def tearDown(self):
        self.client = None
        super(HBSDMIRRORFCDriverTest, self).tearDown()

    # API test cases
    @mock.patch.object(requests.Session, "request")
    @mock.patch.object(
        volume_utils, 'brick_get_connector_properties',
        side_effect=_brick_get_connector_properties)
    def test_do_setup(self, brick_get_connector_properties, request):
        drv = hbsd_fc.HBSDFCDriver(
            configuration=self.configuration)
        self._setup_config()
        self.configuration.hitachi_pair_target_number = 10
        self.configuration.hitachi_mirror_pair_target_number = 20

        def _request_side_effect(
                method, url, params, json, headers, auth, timeout, verify):
            if self.configuration.hitachi_storage_id in url:
                if method == 'POST':
                    return FakeResponse(200, POST_SESSIONS_RESULT)
                elif '/ports' in url:
                    return FakeResponse(200, GET_PORTS_RESULT)
                elif '/host-wwns' in url:
                    return FakeResponse(200, GET_HOST_WWNS_RESULT)
                elif '/host-groups' in url:
                    return FakeResponse(200, GET_HOST_GROUPS_RESULT_PAIR)
            else:
                if method == 'POST':
                    return FakeResponse(200, REMOTE_POST_SESSIONS_RESULT)
                elif '/ports' in url:
                    return FakeResponse(200, REMOTE_GET_PORTS_RESULT)
                elif '/host-wwns' in url:
                    return FakeResponse(200, REMOTE_GET_HOST_WWNS_RESULT)
                elif '/host-groups' in url:
                    return FakeResponse(
                        200, REMOTE_GET_HOST_GROUPS_RESULT_PAIR)
            return FakeResponse(
                500, ERROR_RESULT, headers={'Content-Type': 'json'})
        request.side_effect = _request_side_effect
        drv.do_setup(None)
        self.assertEqual(
            {CONFIG_MAP['port_id']: CONFIG_MAP['target_wwn']},
            drv.common.rep_primary.storage_info['wwns'])
        self.assertEqual(
            {REMOTE_CONFIG_MAP['port_id']: REMOTE_CONFIG_MAP['target_wwn']},
            drv.common.rep_secondary.storage_info['wwns'])
        self.assertEqual(2, brick_get_connector_properties.call_count)
        self.assertEqual(10, request.call_count)
        self.assertEqual(
            "HBSD-pair%2d" % self.configuration.hitachi_pair_target_number,
            drv.common.rep_primary._PAIR_TARGET_NAME)
        self.assertEqual(
            ("HBSD-pair%2d" %
             self.configuration.hitachi_mirror_pair_target_number),
            drv.common.rep_secondary._PAIR_TARGET_NAME)
        # stop the Loopingcall within the do_setup treatment
        drv.common.rep_primary.client.keep_session_loop.stop()
        drv.common.rep_secondary.client.keep_session_loop.stop()
        self._setup_config()

    @mock.patch.object(requests.Session, "request")
    @mock.patch.object(volume_types, 'get_volume_type_extra_specs')
    @mock.patch.object(volume_types, 'get_volume_type_qos_specs')
    def test_create_volume(self, get_volume_type_qos_specs,
                           get_volume_type_extra_specs, request):
        extra_specs = {"test1": "aaa"}
        get_volume_type_extra_specs.return_value = extra_specs
        get_volume_type_qos_specs.return_value = {'qos_specs': None}
        request.return_value = FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)
        self.driver.common.rep_primary._stats = {}
        self.driver.common.rep_primary._stats['pools'] = [
            {'location_info': {'pool_id': 30}}]
        self.driver.common.rep_secondary._stats = {}
        self.driver.common.rep_secondary._stats['pools'] = [
            {'location_info': {'pool_id': 40}}]
        ret = self.driver.create_volume(TEST_VOLUME[7])
        actual = {'provider_location': '1'}
        self.assertEqual(actual, ret)
        self.assertEqual(2, request.call_count)

    @mock.patch.object(requests.Session, "request")
    @mock.patch.object(volume_types, 'get_volume_type_extra_specs')
    @mock.patch.object(volume_types, 'get_volume_type_qos_specs')
    def test_create_volume_replication(self, get_volume_type_qos_specs,
                                       get_volume_type_extra_specs, request):
        extra_specs = {"test1": "aaa",
                       "hbsd:topology": "active_active_mirror_volume"}
        get_volume_type_extra_specs.return_value = extra_specs
        get_volume_type_qos_specs.return_value = {'qos_specs': None}

        def _request_side_effect(
                method, url, params, json, headers, auth, timeout, verify):
            if self.configuration.hitachi_storage_id in url:
                if method in ('POST', 'PUT'):
                    return FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)
                elif method == 'GET':
                    if '/remote-mirror-copygroups' in url:
                        return FakeResponse(200, NOTFOUND_RESULT)
                    elif '/remote-mirror-copypairs/' in url:
                        return FakeResponse(
                            200, GET_REMOTE_MIRROR_COPYPAIR_RESULT)
            else:
                if method in ('POST', 'PUT'):
                    return FakeResponse(202, REMOTE_COMPLETED_SUCCEEDED_RESULT)
                elif method == 'GET':
                    if '/remote-mirror-copygroups' in url:
                        return FakeResponse(200, NOTFOUND_RESULT)
            return FakeResponse(
                500, ERROR_RESULT, headers={'Content-Type': 'json'})
        request.side_effect = _request_side_effect
        self.driver.common.rep_primary._stats = {}
        self.driver.common.rep_primary._stats['pools'] = [
            {'location_info': {'pool_id': 30}}]
        self.driver.common.rep_secondary._stats = {}
        self.driver.common.rep_secondary._stats['pools'] = [
            {'location_info': {'pool_id': 40}}]
        ret = self.driver.create_volume(TEST_VOLUME[3])
        actual = {
            'provider_location': json.dumps(
                {'pldev': 1, 'sldev': 2,
                 'remote-copy': hbsd_utils.MIRROR_ATTR})}
        self.assertEqual(actual, ret)
        self.assertEqual(14, request.call_count)

    @mock.patch.object(requests.Session, "request")
    @mock.patch.object(volume_types, 'get_volume_type_extra_specs')
    @mock.patch.object(volume_types, 'get_volume_type_qos_specs')
    def test_create_volume_replication_qos(
            self, get_volume_type_qos_specs, get_volume_type_extra_specs,
            request):
        input_qos_specs = {
            'qos_specs': {
                'consumer': 'back-end',
                'specs': {'upperIops': '1000'}}}
        get_volume_type_qos_specs.return_value = input_qos_specs
        extra_specs = {"test1": "aaa",
                       "hbsd:topology": "active_active_mirror_volume"}
        get_volume_type_extra_specs.return_value = extra_specs

        def _request_side_effect(
                method, url, params, json, headers, auth, timeout, verify):
            if self.configuration.hitachi_storage_id in url:
                if method in ('POST', 'PUT'):
                    return FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)
                elif method == 'GET':
                    if '/remote-mirror-copygroups' in url:
                        return FakeResponse(200, NOTFOUND_RESULT)
                    elif '/remote-mirror-copypairs/' in url:
                        return FakeResponse(
                            200, GET_REMOTE_MIRROR_COPYPAIR_RESULT)
            else:
                if method in ('POST', 'PUT'):
                    return FakeResponse(202, REMOTE_COMPLETED_SUCCEEDED_RESULT)
                elif method == 'GET':
                    if '/remote-mirror-copygroups' in url:
                        return FakeResponse(200, NOTFOUND_RESULT)
            return FakeResponse(
                500, ERROR_RESULT, headers={'Content-Type': 'json'})
        request.side_effect = _request_side_effect
        self.driver.common.rep_primary._stats = {}
        self.driver.common.rep_primary._stats['pools'] = [
            {'location_info': {'pool_id': 30}}]
        self.driver.common.rep_secondary._stats = {}
        self.driver.common.rep_secondary._stats['pools'] = [
            {'location_info': {'pool_id': 40}}]
        ret = self.driver.create_volume(TEST_VOLUME[3])
        actual = {
            'provider_location': json.dumps(
                {'pldev': 1, 'sldev': 2,
                 'remote-copy': hbsd_utils.MIRROR_ATTR})}
        self.assertEqual(actual, ret)
        self.assertEqual(1, get_volume_type_extra_specs.call_count)
        self.assertEqual(1, get_volume_type_qos_specs.call_count)
        self.assertEqual(16, request.call_count)

    @mock.patch.object(requests.Session, "request")
    def test_delete_volume(self, request):
        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)]
        self.driver.delete_volume(TEST_VOLUME[0])
        self.assertEqual(5, request.call_count)

    @mock.patch.object(requests.Session, "request")
    def test_delete_volume_replication(self, request):
        self.copygroup_count = 0
        self.ldev_count = 0

        def _request_side_effect(
                method, url, params, json, headers, auth, timeout, verify):
            if self.configuration.hitachi_storage_id in url:
                if method in ('POST', 'PUT', 'DELETE'):
                    return FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)
                elif method == 'GET':
                    if '/remote-mirror-copygroups/' in url:
                        if self.copygroup_count < 2:
                            self.copygroup_count = self.copygroup_count + 1
                            return FakeResponse(
                                200, GET_REMOTE_MIRROR_COPYGROUP_RESULT)
                        else:
                            return FakeResponse(
                                500, GET_REMOTE_MIRROR_COPYGROUP_RESULT_ERROR,
                                headers={'Content-Type': 'json'})
                    elif '/remote-mirror-copypairs/' in url:
                        return FakeResponse(
                            200, GET_REMOTE_MIRROR_COPYPAIR_RESULT_SPLIT)
                    elif '/ldevs/' in url:
                        if self.ldev_count == 0:
                            self.ldev_count = self.ldev_count + 1
                            return FakeResponse(200, GET_LDEV_RESULT_REP)
                        else:
                            return FakeResponse(200, GET_LDEV_RESULT_SPLIT)
            else:
                if method in ('POST', 'PUT', 'DELETE'):
                    return FakeResponse(202, REMOTE_COMPLETED_SUCCEEDED_RESULT)
                elif method == 'GET':
                    if '/ldevs/' in url:
                        return FakeResponse(200, GET_LDEV_RESULT_SPLIT)
            return FakeResponse(
                500, ERROR_RESULT, headers={'Content-Type': 'json'})
        request.side_effect = _request_side_effect
        self.driver.delete_volume(TEST_VOLUME[4])
        self.assertEqual(17, request.call_count)

    @mock.patch.object(requests.Session, "request")
    def test_delete_volume_primary_is_invalid_ldev(self, request):
        request.return_value = FakeResponse(200, GET_LDEV_RESULT_LABEL)
        self.driver.delete_volume(TEST_VOLUME[0])
        self.assertEqual(1, request.call_count)

    @mock.patch.object(requests.Session, "request")
    def test_delete_volume_primary_secondary_is_invalid_ldev(self, request):
        request.return_value = FakeResponse(200, GET_LDEV_RESULT_REP_LABEL)
        self.driver.delete_volume(TEST_VOLUME[4])
        self.assertEqual(2, request.call_count)

    @mock.patch.object(requests.Session, "request")
    def test_delete_volume_secondary_is_invalid_ldev(self, request):
        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT_REP_LABEL),
                               FakeResponse(200, GET_LDEV_RESULT_REP),
                               FakeResponse(200, GET_LDEV_RESULT_REP),
                               FakeResponse(200, GET_LDEV_RESULT_REP),
                               FakeResponse(200, GET_LDEV_RESULT_REP),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)]
        self.driver.delete_volume(TEST_VOLUME[4])
        self.assertEqual(6, request.call_count)

    @mock.patch.object(requests.Session, "request")
    def test_extend_volume(self, request):
        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)]
        self.driver.extend_volume(TEST_VOLUME[0], 256)
        self.assertEqual(4, request.call_count)

    @mock.patch.object(requests.Session, "request")
    def test_extend_volume_replication(self, request):
        self.ldev_count = 0
        self.copypair_count = 0

        def _request_side_effect(
                method, url, params, json, headers, auth, timeout, verify):
            if self.configuration.hitachi_storage_id in url:
                if method in ('POST', 'PUT', 'DELETE'):
                    return FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)
                elif method == 'GET':
                    if '/remote-mirror-copygroups/' in url:
                        return FakeResponse(
                            200, GET_REMOTE_MIRROR_COPYGROUP_RESULT)
                    elif '/remote-mirror-copygroups' in url:
                        return FakeResponse(200, NOTFOUND_RESULT)
                    elif '/remote-mirror-copypairs/' in url:
                        if self.copypair_count == 0:
                            self.copypair_count = self.copypair_count + 1
                            return FakeResponse(
                                200, GET_REMOTE_MIRROR_COPYPAIR_RESULT_SPLIT)
                        else:
                            return FakeResponse(
                                200, GET_REMOTE_MIRROR_COPYPAIR_RESULT)
                    elif '/ldevs/' in url:
                        if self.ldev_count < 2:
                            self.ldev_count = self.ldev_count + 1
                            return FakeResponse(200, GET_LDEV_RESULT_REP)
                        else:
                            return FakeResponse(200, GET_LDEV_RESULT)
            else:
                if method in ('POST', 'PUT', 'DELETE'):
                    return FakeResponse(202, REMOTE_COMPLETED_SUCCEEDED_RESULT)
                elif method == 'GET':
                    if '/ldevs/' in url:
                        return FakeResponse(200, GET_LDEV_RESULT)
            return FakeResponse(
                500, ERROR_RESULT, headers={'Content-Type': 'json'})
        request.side_effect = _request_side_effect
        self.driver.extend_volume(TEST_VOLUME[4], 256)
        self.assertEqual(23, request.call_count)

    @mock.patch.object(driver.FibreChannelDriver, "get_goodness_function")
    @mock.patch.object(driver.FibreChannelDriver, "get_filter_function")
    @mock.patch.object(requests.Session, "request")
    def test_get_volume_stats(
            self, request, get_filter_function, get_goodness_function):
        request.return_value = FakeResponse(200, GET_POOLS_RESULT)
        get_filter_function.return_value = None
        get_goodness_function.return_value = None
        stats = self.driver.get_volume_stats(True)
        self.assertEqual('Hitachi', stats['vendor_name'])
        self.assertTrue(stats["pools"][0]['multiattach'])
        self.assertEqual(1, request.call_count)
        self.assertEqual(1, get_filter_function.call_count)
        self.assertEqual(1, get_goodness_function.call_count)

    @mock.patch.object(requests.Session, "request")
    @mock.patch.object(volume_types, 'get_volume_type_extra_specs')
    @mock.patch.object(sqlalchemy_api, 'volume_get', side_effect=_volume_get)
    @mock.patch.object(volume_types, 'get_volume_type_qos_specs')
    def test_create_snapshot(
            self, get_volume_type_qos_specs, volume_get,
            get_volume_type_extra_specs, request):
        extra_specs = {"test1": "aaa",
                       "hbsd:topology": "active_active_mirror_volume"}
        get_volume_type_extra_specs.return_value = extra_specs
        get_volume_type_qos_specs.return_value = {'qos_specs': None}
        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(200, GET_SNAPSHOTS_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)]
        self.driver.common.rep_primary._stats = {}
        self.driver.common.rep_primary._stats['pools'] = [
            {'location_info': {'pool_id': 30}}]
        self.driver.common.rep_secondary._stats = {}
        self.driver.common.rep_secondary._stats['pools'] = [
            {'location_info': {'pool_id': 40}}]
        ret = self.driver.create_snapshot(TEST_SNAPSHOT[0])
        actual = {'provider_location': '1'}
        self.assertEqual(actual, ret)
        self.assertEqual(5, request.call_count)

    @mock.patch.object(requests.Session, "request")
    def test_delete_snapshot(self, request):
        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT_PAIR),
                               FakeResponse(200, NOTFOUND_RESULT),
                               FakeResponse(200, GET_SNAPSHOTS_RESULT),
                               FakeResponse(200, GET_SNAPSHOTS_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)]
        self.driver.delete_snapshot(TEST_SNAPSHOT[0])
        self.assertEqual(14, request.call_count)

    @mock.patch.object(requests.Session, "request")
    def test_delete_snapshot_pldev_in_loc(self, request):
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.delete_snapshot,
                          TEST_SNAPSHOT[1])
        self.assertEqual(1, request.call_count)

    @mock.patch.object(requests.Session, "request")
    def test_delete_snapshot_snapshot_is_busy(self, request):
        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT_PAIR),
                               FakeResponse(200, NOTFOUND_RESULT),
                               FakeResponse(200, GET_SNAPSHOTS_RESULT_TEST)]
        self.assertRaises(exception.SnapshotIsBusy,
                          self.driver.delete_snapshot,
                          TEST_SNAPSHOT[0])
        self.assertEqual(3, request.call_count)

    @mock.patch.object(requests.Session, "request")
    @mock.patch.object(volume_types, 'get_volume_type_extra_specs')
    @mock.patch.object(volume_types, 'get_volume_type_qos_specs')
    def test_create_cloned_volume(
            self, get_volume_type_qos_specs, get_volume_type_extra_specs,
            request):
        extra_specs = {"test1": "aaa"}
        get_volume_type_extra_specs.return_value = extra_specs
        get_volume_type_qos_specs.return_value = {'qos_specs': None}
        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(200, GET_SNAPSHOTS_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)]
        self.driver.common.rep_primary._stats = {}
        self.driver.common.rep_primary._stats['pools'] = [
            {'location_info': {'pool_id': 30}}]
        self.driver.common.rep_secondary._stats = {}
        self.driver.common.rep_secondary._stats['pools'] = [
            {'location_info': {'pool_id': 40}}]
        ret = self.driver.create_cloned_volume(TEST_VOLUME[0], TEST_VOLUME[1])
        actual = {'provider_location': '1'}
        self.assertEqual(actual, ret)
        self.assertEqual(5, request.call_count)

    @mock.patch.object(requests.Session, "request")
    @mock.patch.object(volume_types, 'get_volume_type_extra_specs')
    @mock.patch.object(volume_types, 'get_volume_type_qos_specs')
    def test_create_cloned_volume_replication(
            self, get_volume_type_qos_specs, get_volume_type_extra_specs,
            request):
        extra_specs = {"hbsd:topology": "active_active_mirror_volume"}
        get_volume_type_extra_specs.return_value = extra_specs
        get_volume_type_qos_specs.return_value = {'qos_specs': None}
        self.snapshot_count = 0

        def _request_side_effect(
                method, url, params, json, headers, auth, timeout, verify):
            if self.configuration.hitachi_storage_id in url:
                if method in ('POST', 'PUT'):
                    return FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)
                elif method == 'GET':
                    if '/remote-mirror-copygroups' in url:
                        return FakeResponse(200, NOTFOUND_RESULT)
                    elif '/remote-mirror-copypairs/' in url:
                        return FakeResponse(
                            200, GET_REMOTE_MIRROR_COPYPAIR_RESULT)
                    elif '/ldevs/' in url:
                        return FakeResponse(200, GET_LDEV_RESULT_REP)
                    elif '/snapshots' in url:
                        if self.snapshot_count < 1:
                            self.snapshot_count = self.snapshot_count + 1
                            return FakeResponse(200, GET_SNAPSHOTS_RESULT)
                        else:
                            return FakeResponse(200, NOTFOUND_RESULT)
            else:
                if method in ('POST', 'PUT'):
                    return FakeResponse(202, REMOTE_COMPLETED_SUCCEEDED_RESULT)
                elif method == 'GET':
                    if '/remote-mirror-copygroups' in url:
                        return FakeResponse(200, NOTFOUND_RESULT)
            return FakeResponse(
                500, ERROR_RESULT, headers={'Content-Type': 'json'})
        request.side_effect = _request_side_effect
        self.driver.common.rep_primary._stats = {}
        self.driver.common.rep_primary._stats['pools'] = [
            {'location_info': {'pool_id': 30}}]
        self.driver.common.rep_secondary._stats = {}
        self.driver.common.rep_secondary._stats['pools'] = [
            {'location_info': {'pool_id': 40}}]
        ret = self.driver.create_cloned_volume(TEST_VOLUME[4], TEST_VOLUME[5])
        actual = {
            'provider_location': json.dumps(
                {'pldev': 1, 'sldev': 2,
                 'remote-copy': hbsd_utils.MIRROR_ATTR})}
        self.assertEqual(actual, ret)
        self.assertEqual(23, request.call_count)

    @mock.patch.object(requests.Session, "request")
    @mock.patch.object(volume_types, 'get_volume_type_extra_specs')
    @mock.patch.object(volume_types, 'get_volume_type_qos_specs')
    def test_create_volume_from_snapshot(
            self, get_volume_type_qos_specs, get_volume_type_extra_specs,
            request):
        extra_specs = {"test1": "aaa"}
        get_volume_type_extra_specs.return_value = extra_specs
        get_volume_type_qos_specs.return_value = {'qos_specs': None}
        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(200, GET_SNAPSHOTS_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)]
        self.driver.common.rep_primary._stats = {}
        self.driver.common.rep_primary._stats['pools'] = [
            {'location_info': {'pool_id': 30}}]
        self.driver.common.rep_secondary._stats = {}
        self.driver.common.rep_secondary._stats['pools'] = [
            {'location_info': {'pool_id': 40}}]
        ret = self.driver.create_volume_from_snapshot(
            TEST_VOLUME[0], TEST_SNAPSHOT[0])
        actual = {'provider_location': '1'}
        self.assertEqual(actual, ret)
        self.assertEqual(5, request.call_count)

    @mock.patch.object(fczm_utils, "add_fc_zone")
    @mock.patch.object(requests.Session, "request")
    @mock.patch.object(volume_types, 'get_volume_type_extra_specs')
    def test_initialize_connection(
            self, get_volume_type_extra_specs, request, add_fc_zone):
        self.driver.common.conf.hitachi_zoning_request = True
        self.driver.common.rep_primary.lookup_service = FakeLookupService()
        self.driver.common.rep_secondary.lookup_service = FakeLookupService()
        extra_specs = {"test1": "aaa"}
        get_volume_type_extra_specs.return_value = extra_specs
        def _request_side_effect(
                method, url, params, json, headers, auth, timeout, verify):
            if self.configuration.hitachi_storage_id in url:
                if method in ('POST', 'PUT'):
                    return FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)
                elif method == 'GET':
                    return FakeResponse(200, GET_HOST_WWNS_RESULT)
            else:
                if method in ('POST', 'PUT'):
                    return FakeResponse(202, REMOTE_COMPLETED_SUCCEEDED_RESULT)
                elif method == 'GET':
                    return FakeResponse(200, REMOTE_GET_HOST_WWNS_RESULT)
            return FakeResponse(
                500, ERROR_RESULT, headers={'Content-Type': 'json'})
        request.side_effect = _request_side_effect
        ret = self.driver.initialize_connection(
            TEST_VOLUME[4], DEFAULT_CONNECTOR)
        self.assertEqual('fibre_channel', ret['driver_volume_type'])
        self.assertEqual(
            [CONFIG_MAP['target_wwn'], REMOTE_CONFIG_MAP['target_wwn']],
            ret['data']['target_wwn'])
        self.assertEqual(1, ret['data']['target_lun'])
        self.assertEqual(4, request.call_count)
        self.assertEqual(1, add_fc_zone.call_count)

    @mock.patch.object(fczm_utils, "remove_fc_zone")
    @mock.patch.object(requests.Session, "request")
    def test_terminate_connection(self, request, remove_fc_zone):
        self.driver.common.conf.hitachi_zoning_request = True
        self.driver.common.rep_primary.lookup_service = FakeLookupService()
        self.driver.common.rep_secondary.lookup_service = FakeLookupService()
        def _request_side_effect(
                method, url, params, json, headers, auth, timeout, verify):
            if self.configuration.hitachi_storage_id in url:
                if method in ('POST', 'PUT', 'DELETE'):
                    return FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)
                elif method == 'GET':
                    if '/ldevs/' in url:
                        return FakeResponse(200, GET_LDEV_RESULT_MAPPED)
                    elif '/host-wwns' in url:
                        return FakeResponse(200, GET_HOST_WWNS_RESULT)
                    else:
                        return FakeResponse(200, NOTFOUND_RESULT)
            else:
                if method in ('POST', 'PUT', 'DELETE'):
                    return FakeResponse(202, REMOTE_COMPLETED_SUCCEEDED_RESULT)
                elif method == 'GET':
                    if '/ldevs/' in url:
                        return FakeResponse(200, REMOTE_GET_LDEV_RESULT_MAPPED)
                    elif '/host-wwns' in url:
                        return FakeResponse(200, REMOTE_GET_HOST_WWNS_RESULT)
                    else:
                        return FakeResponse(200, NOTFOUND_RESULT)
            return FakeResponse(
                500, ERROR_RESULT, headers={'Content-Type': 'json'})
        request.side_effect = _request_side_effect
        self.driver.terminate_connection(TEST_VOLUME[6], DEFAULT_CONNECTOR)
        self.assertEqual(10, request.call_count)
        self.assertEqual(1, remove_fc_zone.call_count)

    @mock.patch.object(fczm_utils, "add_fc_zone")
    @mock.patch.object(requests.Session, "request")
    def test_initialize_connection_snapshot(self, request, add_fc_zone):
        self.driver.common.rep_primary.conf.hitachi_zoning_request = True
        self.driver.common.lookup_service = FakeLookupService()
        request.side_effect = [FakeResponse(200, GET_HOST_WWNS_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)]
        ret = self.driver.initialize_connection_snapshot(
            TEST_SNAPSHOT[0], DEFAULT_CONNECTOR)
        self.assertEqual('fibre_channel', ret['driver_volume_type'])
        self.assertEqual([CONFIG_MAP['target_wwn']], ret['data']['target_wwn'])
        self.assertEqual(1, ret['data']['target_lun'])
        self.assertEqual(2, request.call_count)
        self.assertEqual(1, add_fc_zone.call_count)

    @mock.patch.object(fczm_utils, "remove_fc_zone")
    @mock.patch.object(requests.Session, "request")
    def test_terminate_connection_snapshot(self, request, remove_fc_zone):
        self.driver.common.rep_primary.conf.hitachi_zoning_request = True
        self.driver.common.lookup_service = FakeLookupService()
        request.side_effect = [FakeResponse(200, GET_HOST_WWNS_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT_MAPPED),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(200, NOTFOUND_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)]
        self.driver.terminate_connection_snapshot(
            TEST_SNAPSHOT[0], DEFAULT_CONNECTOR)
        self.assertEqual(5, request.call_count)
        self.assertEqual(1, remove_fc_zone.call_count)

    @mock.patch.object(requests.Session, "request")
    @mock.patch.object(volume_types, 'get_volume_type_qos_specs')
    def test_manage_existing(self, get_volume_type_qos_specs, request):
        get_volume_type_qos_specs.return_value = {'qos_specs': None}
        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(200, GET_LDEVS_RESULT)]
        ret = self.driver.manage_existing(
            TEST_VOLUME[0], self.test_existing_ref)
        actual = {'provider_location': '1'}
        self.assertEqual(actual, ret)
        self.assertEqual(3, request.call_count)

    @mock.patch.object(requests.Session, "request")
    @mock.patch.object(volume_types, 'get_volume_type_extra_specs')
    def test_manage_existing_get_size(
            self, get_volume_type_extra_specs, request):
        extra_specs = {"test1": "aaa"}
        get_volume_type_extra_specs.return_value = extra_specs
        request.return_value = FakeResponse(200, GET_LDEV_RESULT)
        self.driver.manage_existing_get_size(
            TEST_VOLUME[0], self.test_existing_ref)
        self.assertEqual(1, request.call_count)

    @mock.patch.object(requests.Session, "request")
    def test_unmanage(self, request):
        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT)]
        self.driver.unmanage(TEST_VOLUME[0])
        self.assertEqual(3, request.call_count)

    @mock.patch.object(requests.Session, "request")
    def test_unmanage_has_rep_pair_true(self, request):
        request.return_value = FakeResponse(200, GET_LDEV_RESULT_REP)
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.unmanage,
                          TEST_VOLUME[4])
        self.assertEqual(1, request.call_count)

    @mock.patch.object(requests.Session, "request")
    def test_copy_image_to_volume(self, request):
        image_service = 'fake_image_service'
        image_id = 'fake_image_id'
        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, COMPLETED_SUCCEEDED_RESULT)]
        with mock.patch.object(driver.VolumeDriver, 'copy_image_to_volume') \
                as mock_copy_image:
            self.driver.copy_image_to_volume(
                self.ctxt, TEST_VOLUME[0], image_service, image_id)
        mock_copy_image.assert_called_with(
            self.ctxt, TEST_VOLUME[0], image_service, image_id,
            disable_sparse=False)
        self.assertEqual(2, request.call_count)

    @mock.patch.object(requests.Session, "request")
    def test_update_migrated_volume(self, request):
        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)]
        ret = self.driver.update_migrated_volume(
            self.ctxt, TEST_VOLUME[0], TEST_VOLUME[1], "available")
        self.assertEqual(2, request.call_count)
        actual = ({'_name_id': TEST_VOLUME[1]['id'],
                   'provider_location': TEST_VOLUME[1]['provider_location']})
        self.assertEqual(actual, ret)

    @mock.patch.object(requests.Session, "request")
    def test_update_migrated_volume_replication(self, request):
        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT_REP),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)]
        ret = self.driver.update_migrated_volume(
            self.ctxt, TEST_VOLUME[0], TEST_VOLUME[4], "available")
        self.assertEqual(3, request.call_count)
        actual = ({'_name_id': TEST_VOLUME[4]['id'],
                   'provider_location': TEST_VOLUME[4]['provider_location']})
        self.assertEqual(actual, ret)

    def test_unmanage_snapshot(self):
        """The driver don't support unmange_snapshot."""
        self.assertRaises(
            NotImplementedError,
            self.driver.unmanage_snapshot,
            TEST_SNAPSHOT[0])

    @mock.patch.object(requests.Session, "request")
    @mock.patch.object(volume_types, 'get_volume_type_extra_specs')
    @mock.patch.object(obj_snap.SnapshotList, 'get_all_for_volume')
    def test_retype(self, get_all_for_volume,
                    get_volume_type_extra_specs, request):
        extra_specs = {'test1': 'aaa',
                       'hbsd:target_ports': 'CL2-A'}
        get_volume_type_extra_specs.return_value = extra_specs
        get_all_for_volume.return_value = True

        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT)]

        old_specs = {'hbsd:target_ports': 'CL1-A'}
        new_specs = {'hbsd:target_ports': 'CL2-A'}
        old_type_ref = volume_types.create(self.ctxt, 'old', old_specs)
        new_type_ref = volume_types.create(self.ctxt, 'new', new_specs)
        new_type = volume_types.get_volume_type(self.ctxt, new_type_ref['id'])

        diff = volume_types.volume_types_diff(self.ctxt, old_type_ref['id'],
                                              new_type_ref['id'])[0]
        host = {
            'capabilities': {
                'location_info': {
                    'pool_id': 30,
                },
            },
        }

        ret = self.driver.retype(
            self.ctxt, TEST_VOLUME[0], new_type, diff, host)
        self.assertEqual(2, request.call_count)
        self.assertFalse(ret)

    @mock.patch.object(requests.Session, "request")
    @mock.patch.object(volume_types, 'get_volume_type_extra_specs')
    def test_retype_replication(self, get_volume_type_extra_specs, request):
        extra_specs = {'test1': 'aaa',
                       'hbsd:topology': 'active_active_mirror_volume'}
        get_volume_type_extra_specs.return_value = extra_specs

        request.return_value = FakeResponse(200, GET_LDEV_RESULT)

        new_type_ref = volume_types.create(self.ctxt, 'new', extra_specs)
        new_type = volume_types.get_volume_type(self.ctxt, new_type_ref['id'])
        diff = {}
        host = {
            'capabilities': {
                'location_info': {
                    'pool_id': 30,
                },
            },
        }
        ret = self.driver.retype(
            self.ctxt, TEST_VOLUME[0], new_type, diff, host)
        self.assertEqual(1, request.call_count)
        self.assertFalse(ret)

    @mock.patch.object(requests.Session, "request")
    def test_migrate_volume(
            self, request):
        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT)]
        host = {
            'capabilities': {
                'location_info': {
                    'storage_id': CONFIG_MAP['serial'],
                    'pool_id': 30,
                },
            },
        }
        ret = self.driver.migrate_volume(self.ctxt, TEST_VOLUME[0], host)
        self.assertEqual(3, request.call_count)
        actual = (True, None)
        self.assertTupleEqual(actual, ret)

    @mock.patch.object(requests.Session, "request")
    def test_revert_to_snapshot(self, request):
        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT_PAIR),
                               FakeResponse(200, GET_LDEV_RESULT_PAIR),
                               FakeResponse(200, GET_LDEV_RESULT_PAIR),
                               FakeResponse(200, GET_LDEV_RESULT_PAIR),
                               FakeResponse(200, GET_SNAPSHOTS_RESULT),
                               FakeResponse(200, GET_SNAPSHOTS_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(200, GET_SNAPSHOTS_RESULT)]
        self.driver.revert_to_snapshot(
            self.ctxt, TEST_VOLUME[0], TEST_SNAPSHOT[0])
        self.assertEqual(8, request.call_count)

    def test_create_group(self):
        ret = self.driver.create_group(self.ctxt, TEST_GROUP[0])
        self.assertIsNone(ret)

    @mock.patch.object(requests.Session, "request")
    def test_delete_group(self, request):
        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)]
        ret = self.driver.delete_group(
            self.ctxt, TEST_GROUP[0], [TEST_VOLUME[0]])
        self.assertEqual(5, request.call_count)
        actual = (
            {'status': TEST_GROUP[0]['status']},
            [{'id': TEST_VOLUME[0]['id'], 'status': 'deleted'}]
        )
        self.assertTupleEqual(actual, ret)

    @mock.patch.object(requests.Session, "request")
    @mock.patch.object(volume_types, 'get_volume_type_extra_specs')
    @mock.patch.object(volume_types, 'get_volume_type_qos_specs')
    def test_create_group_from_src_volume(
            self, get_volume_type_qos_specs, get_volume_type_extra_specs,
            request):
        extra_specs = {"test1": "aaa"}
        get_volume_type_extra_specs.return_value = extra_specs
        get_volume_type_qos_specs.return_value = {'qos_specs': None}
        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(200, GET_SNAPSHOTS_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)]
        self.driver.common.rep_primary._stats = {}
        self.driver.common.rep_primary._stats['pools'] = [
            {'location_info': {'pool_id': 30}}]
        self.driver.common.rep_secondary._stats = {}
        self.driver.common.rep_secondary._stats['pools'] = [
            {'location_info': {'pool_id': 40}}]
        ret = self.driver.create_group_from_src(
            self.ctxt, TEST_GROUP[1], [TEST_VOLUME[1]],
            source_group=TEST_GROUP[0], source_vols=[TEST_VOLUME[0]]
        )
        self.assertEqual(5, request.call_count)
        actual = (
            None,
            [{'id': TEST_VOLUME[1]['id'],
              'provider_location': '1'}])
        self.assertTupleEqual(actual, ret)

    @mock.patch.object(requests.Session, "request")
    @mock.patch.object(volume_types, 'get_volume_type_extra_specs')
    @mock.patch.object(volume_types, 'get_volume_type_qos_specs')
    def test_create_group_from_src_Exception(
            self, get_volume_type_qos_specs, get_volume_type_extra_specs,
            request):
        extra_specs = {"test1": "aaa"}
        get_volume_type_extra_specs.return_value = extra_specs
        get_volume_type_qos_specs.return_value = {'qos_specs': None}
        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(200, GET_SNAPSHOTS_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)]
        self.driver.common.rep_primary._stats = {}
        self.driver.common.rep_primary._stats['pools'] = [
            {'location_info': {'pool_id': 30}}]
        self.driver.common.rep_secondary._stats = {}
        self.driver.common.rep_secondary._stats['pools'] = [
            {'location_info': {'pool_id': 40}}]
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.create_group_from_src,
                          self.ctxt, TEST_GROUP[1],
                          [TEST_VOLUME[1], TEST_VOLUME[1]],
                          source_group=TEST_GROUP[0],
                          source_vols=[TEST_VOLUME[0], TEST_VOLUME[3]]
                          )
        self.assertEqual(10, request.call_count)

    @mock.patch.object(requests.Session, "request")
    @mock.patch.object(volume_types, 'get_volume_type_extra_specs')
    @mock.patch.object(volume_types, 'get_volume_type_qos_specs')
    def test_create_group_from_src_snapshot(
            self, get_volume_type_qos_specs, get_volume_type_extra_specs,
            request):
        extra_specs = {"test1": "aaa"}
        get_volume_type_extra_specs.return_value = extra_specs
        get_volume_type_qos_specs.return_value = {'qos_specs': None}
        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(200, GET_SNAPSHOTS_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)]
        self.driver.common.rep_primary._stats = {}
        self.driver.common.rep_primary._stats['pools'] = [
            {'location_info': {'pool_id': 30}}]
        self.driver.common.rep_secondary._stats = {}
        self.driver.common.rep_secondary._stats['pools'] = [
            {'location_info': {'pool_id': 40}}]
        ret = self.driver.create_group_from_src(
            self.ctxt, TEST_GROUP[0], [TEST_VOLUME[0]],
            group_snapshot=TEST_GROUP_SNAP[0], snapshots=[TEST_SNAPSHOT[0]]
        )
        self.assertEqual(5, request.call_count)
        actual = (
            None,
            [{'id': TEST_VOLUME[0]['id'],
              'provider_location': '1'}])
        self.assertTupleEqual(actual, ret)

    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type')
    def test_update_group(self, is_group_a_cg_snapshot_type):
        is_group_a_cg_snapshot_type.return_value = False
        ret = self.driver.update_group(
            self.ctxt, TEST_GROUP[0], add_volumes=[TEST_VOLUME[0]])
        self.assertTupleEqual((None, None, None), ret)

    @mock.patch.object(requests.Session, "request")
    @mock.patch.object(volume_types, 'get_volume_type_extra_specs')
    @mock.patch.object(sqlalchemy_api, 'volume_get', side_effect=_volume_get)
    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type')
    @mock.patch.object(volume_types, 'get_volume_type_qos_specs')
    def test_create_group_snapshot_non_cg(
            self, get_volume_type_qos_specs, is_group_a_cg_snapshot_type,
            volume_get, get_volume_type_extra_specs, request):
        is_group_a_cg_snapshot_type.return_value = False
        extra_specs = {"test1": "aaa"}
        get_volume_type_extra_specs.return_value = extra_specs
        get_volume_type_qos_specs.return_value = {'qos_specs': None}
        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(200, GET_SNAPSHOTS_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)]
        self.driver.common.rep_primary._stats = {}
        self.driver.common.rep_primary._stats['pools'] = [
            {'location_info': {'pool_id': 30}}]
        self.driver.common.rep_secondary._stats = {}
        self.driver.common.rep_secondary._stats['pools'] = [
            {'location_info': {'pool_id': 40}}]
        ret = self.driver.create_group_snapshot(
            self.ctxt, TEST_GROUP_SNAP[0], [TEST_SNAPSHOT[0]]
        )
        self.assertEqual(5, request.call_count)
        actual = (
            {'status': 'available'},
            [{'id': TEST_SNAPSHOT[0]['id'],
              'provider_location': '1',
              'status': 'available'}]
        )
        self.assertTupleEqual(actual, ret)

    @mock.patch.object(requests.Session, "request")
    def test_delete_group_snapshot(self, request):
        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT_PAIR),
                               FakeResponse(200, NOTFOUND_RESULT),
                               FakeResponse(200, GET_SNAPSHOTS_RESULT),
                               FakeResponse(200, GET_SNAPSHOTS_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)]
        ret = self.driver.delete_group_snapshot(
            self.ctxt, TEST_GROUP_SNAP[0], [TEST_SNAPSHOT[0]])
        self.assertEqual(14, request.call_count)
        actual = (
            {'status': TEST_GROUP_SNAP[0]['status']},
            [{'id': TEST_SNAPSHOT[0]['id'], 'status': 'deleted'}]
        )
        self.assertTupleEqual(actual, ret)

    @mock.patch.object(requests.Session, "request")
    @mock.patch.object(volume_types, 'get_volume_type_extra_specs')
    @mock.patch.object(volume_types, 'get_volume_type_qos_specs')
    def test_create_rep_ldev_and_pair_deduplication_compression(
            self, get_volume_type_qos_specs, get_volume_type_extra_specs,
            request):
        get_volume_type_extra_specs.return_value = {
            'hbsd:topology': 'active_active_mirror_volume',
            'hbsd:capacity_saving': 'deduplication_compression'}
        get_volume_type_qos_specs.return_value = {'qos_specs': None}
        self.snapshot_count = 0

        def _request_side_effect(
                method, url, params, json, headers, auth, timeout, verify):
            if self.configuration.hitachi_storage_id in url:
                if method in ('POST', 'PUT'):
                    return FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)
                elif method == 'GET':
                    if ('/remote-mirror-copygroups' in url or
                            '/journals' in url):
                        return FakeResponse(200, NOTFOUND_RESULT)
                    elif '/remote-mirror-copypairs/' in url:
                        return FakeResponse(
                            200, GET_REMOTE_MIRROR_COPYPAIR_RESULT)
                    elif '/ldevs/' in url:
                        return FakeResponse(200, GET_LDEV_RESULT_REP)
                    elif '/snapshots' in url:
                        if self.snapshot_count < 1:
                            self.snapshot_count = self.snapshot_count + 1
                            return FakeResponse(200, GET_SNAPSHOTS_RESULT)
                        else:
                            return FakeResponse(200, NOTFOUND_RESULT)
            else:
                if method in ('POST', 'PUT'):
                    return FakeResponse(400, REMOTE_COMPLETED_SUCCEEDED_RESULT)
                elif method == 'GET':
                    if '/remote-mirror-copygroups' in url:
                        return FakeResponse(200, NOTFOUND_RESULT)
                    elif '/ldevs/' in url:
                        return FakeResponse(200, GET_LDEV_RESULT_REP)
            if '/ldevs/' in url:
                return FakeResponse(200, GET_LDEV_RESULT_REP)
            else:
                return FakeResponse(
                    200, COMPLETED_SUCCEEDED_RESULT)
        self.driver.common.rep_primary._stats = {}
        self.driver.common.rep_primary._stats['pools'] = [
            {'location_info': {'pool_id': 30}}]
        self.driver.common.rep_secondary._stats = {}
        self.driver.common.rep_secondary._stats['pools'] = [
            {'location_info': {'pool_id': 40}}]
        request.side_effect = _request_side_effect
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.create_cloned_volume,
                          TEST_VOLUME[4],
                          TEST_VOLUME[5])
        self.assertEqual(2, get_volume_type_extra_specs.call_count)
        self.assertEqual(1, get_volume_type_qos_specs.call_count)
        self.assertEqual(14, request.call_count)
