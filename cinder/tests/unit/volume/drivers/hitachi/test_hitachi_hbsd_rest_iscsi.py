# Copyright (C) 2020, Hitachi, Ltd.
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

from unittest import mock

from oslo_config import cfg
import requests

from cinder import context as cinder_context
from cinder.db.sqlalchemy import api as sqlalchemy_api
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
from cinder.volume.drivers.hitachi import hbsd_iscsi
from cinder.volume.drivers.hitachi import hbsd_rest
from cinder.volume.drivers.hitachi import hbsd_utils
from cinder.volume import volume_types
from cinder.volume import volume_utils

# Configuration parameter values
CONFIG_MAP = {
    'serial': '886000123456',
    'my_ip': '127.0.0.1',
    'rest_server_ip_addr': '172.16.18.108',
    'rest_server_ip_port': '23451',
    'port_id': 'CL1-A',
    'host_grp_name': 'HBSD-127.0.0.1',
    'host_mode': 'LINUX/IRIX',
    'host_iscsi_name': 'iqn.hbsd-test-host',
    'target_iscsi_name': 'iqn.hbsd-test-target',
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

CTXT = cinder_context.get_admin_context()

TEST_VOLUME = []
for i in range(4):
    volume = {}
    volume['id'] = '00000000-0000-0000-0000-{0:012d}'.format(i)
    volume['name'] = 'test-volume{0:d}'.format(i)
    if i == 3:
        volume['provider_location'] = None
    else:
        volume['provider_location'] = '{0:d}'.format(i)
    volume['size'] = 128
    if i == 2:
        volume['status'] = 'in-use'
    else:
        volume['status'] = 'available'
    volume = fake_volume.fake_volume_obj(CTXT, **volume)
    TEST_VOLUME.append(volume)


def _volume_get(context, volume_id):
    """Return predefined volume info."""
    return TEST_VOLUME[int(volume_id.replace("-", ""))]


TEST_SNAPSHOT = []
snapshot = {}
snapshot['id'] = '10000000-0000-0000-0000-{0:012d}'.format(0)
snapshot['name'] = 'TEST_SNAPSHOT{0:d}'.format(0)
snapshot['provider_location'] = '{0:d}'.format(1)
snapshot['status'] = 'available'
snapshot['volume_id'] = '00000000-0000-0000-0000-{0:012d}'.format(0)
snapshot['volume'] = _volume_get(None, snapshot['volume_id'])
snapshot['volume_name'] = 'test-volume{0:d}'.format(0)
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
            "hostGroupName": "HBSD-test",
            "iscsiName": CONFIG_MAP['target_iscsi_name'],
        },
    ],
}

COMPLETED_SUCCEEDED_RESULT = {
    "status": "Completed",
    "state": "Succeeded",
    "affectedResources": ('a/b/c/1',),
}

GET_LDEV_RESULT = {
    "emulationType": "OPEN-V-CVS",
    "blockCapacity": 2097152,
    "attributes": ["CVS", "HDP"],
    "status": "NML",
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

GET_LDEV_RESULT_PAIR = {
    "emulationType": "OPEN-V-CVS",
    "blockCapacity": 2097152,
    "attributes": ["CVS", "HDP", "HTI"],
    "status": "NML",
}

GET_POOL_RESULT = {
    "availableVolumeCapacity": 480144,
    "totalPoolCapacity": 507780,
    "totalLocatedCapacity": 71453172,
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

NOTFOUND_RESULT = {
    "data": [],
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


class HBSDRESTISCSIDriverTest(test.TestCase):
    """Unit test class for HBSD REST interface iSCSI module."""

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
        super(HBSDRESTISCSIDriverTest, self).setUp()
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
            "cinder.volume.drivers.hitachi.hbsd_iscsi.HBSDISCSIDriver")
        self.configuration.reserved_percentage = "0"
        self.configuration.use_multipath_for_image_xfer = False
        self.configuration.enforce_multipath_for_image_xfer = False
        self.configuration.max_over_subscription_ratio = 500.0
        self.configuration.driver_ssl_cert_verify = False

        self.configuration.hitachi_storage_id = CONFIG_MAP['serial']
        self.configuration.hitachi_pool = "30"
        self.configuration.hitachi_snap_pool = None
        self.configuration.hitachi_ldev_range = "0-1"
        self.configuration.hitachi_target_ports = [CONFIG_MAP['port_id']]
        self.configuration.hitachi_compute_target_ports = [
            CONFIG_MAP['port_id']]
        self.configuration.hitachi_group_create = True
        self.configuration.hitachi_group_delete = True

        self.configuration.san_login = CONFIG_MAP['user_id']
        self.configuration.san_password = CONFIG_MAP['user_pass']
        self.configuration.san_ip = CONFIG_MAP[
            'rest_server_ip_addr']
        self.configuration.san_api_port = CONFIG_MAP[
            'rest_server_ip_port']
        self.configuration.hitachi_rest_tcp_keepalive = True
        self.configuration.hitachi_discard_zero_page = True
        self.configuration.hitachi_rest_number = "0"

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
        self.driver = hbsd_iscsi.HBSDISCSIDriver(
            configuration=self.configuration)
        request.side_effect = [FakeResponse(200, POST_SESSIONS_RESULT),
                               FakeResponse(200, GET_PORTS_RESULT),
                               FakeResponse(200, GET_PORT_RESULT),
                               FakeResponse(200, GET_HOST_ISCSIS_RESULT),
                               FakeResponse(200, GET_HOST_GROUP_RESULT)]
        self.driver.do_setup(None)
        self.driver.check_for_setup_error()
        self.driver.local_path(None)
        self.driver.create_export(None, None, None)
        self.driver.ensure_export(None, None)
        self.driver.remove_export(None, None)
        self.driver.create_export_snapshot(None, None, None)
        self.driver.remove_export_snapshot(None, None)
        # stop the Loopingcall within the do_setup treatment
        self.driver.common.client.keep_session_loop.stop()

    def tearDown(self):
        self.client = None
        super(HBSDRESTISCSIDriverTest, self).tearDown()

    # API test cases
    @mock.patch.object(requests.Session, "request")
    @mock.patch.object(
        volume_utils, 'brick_get_connector_properties',
        side_effect=_brick_get_connector_properties)
    def test_do_setup(self, brick_get_connector_properties, request):
        drv = hbsd_iscsi.HBSDISCSIDriver(
            configuration=self.configuration)
        self._setup_config()
        request.side_effect = [FakeResponse(200, POST_SESSIONS_RESULT),
                               FakeResponse(200, GET_PORTS_RESULT),
                               FakeResponse(200, GET_PORT_RESULT),
                               FakeResponse(200, GET_HOST_ISCSIS_RESULT),
                               FakeResponse(200, GET_HOST_GROUP_RESULT)]
        drv.do_setup(None)
        self.assertEqual(
            {CONFIG_MAP['port_id']:
                '%(ip)s:%(port)s' % {
                    'ip': CONFIG_MAP['ipv4Address'],
                    'port': CONFIG_MAP['tcpPort']}},
            drv.common.storage_info['portals'])
        self.assertEqual(1, brick_get_connector_properties.call_count)
        self.assertEqual(5, request.call_count)
        # stop the Loopingcall within the do_setup treatment
        self.driver.common.client.keep_session_loop.stop()
        self.driver.common.client.keep_session_loop.wait()

    @mock.patch.object(requests.Session, "request")
    @mock.patch.object(
        volume_utils, 'brick_get_connector_properties',
        side_effect=_brick_get_connector_properties)
    def test_do_setup_create_hg(self, brick_get_connector_properties, request):
        """Normal case: The host group not exists."""
        drv = hbsd_iscsi.HBSDISCSIDriver(
            configuration=self.configuration)
        self._setup_config()
        request.side_effect = [FakeResponse(200, POST_SESSIONS_RESULT),
                               FakeResponse(200, GET_PORTS_RESULT),
                               FakeResponse(200, GET_PORT_RESULT),
                               FakeResponse(200, NOTFOUND_RESULT),
                               FakeResponse(200, NOTFOUND_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)]
        drv.do_setup(None)
        self.assertEqual(
            {CONFIG_MAP['port_id']:
                '%(ip)s:%(port)s' % {
                    'ip': CONFIG_MAP['ipv4Address'],
                    'port': CONFIG_MAP['tcpPort']}},
            drv.common.storage_info['portals'])
        self.assertEqual(1, brick_get_connector_properties.call_count)
        self.assertEqual(8, request.call_count)
        # stop the Loopingcall within the do_setup treatment
        self.driver.common.client.keep_session_loop.stop()
        self.driver.common.client.keep_session_loop.wait()

    @mock.patch.object(requests.Session, "request")
    def test_extend_volume(self, request):
        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)]
        self.driver.extend_volume(TEST_VOLUME[0], 256)
        self.assertEqual(3, request.call_count)

    @mock.patch.object(driver.ISCSIDriver, "get_goodness_function")
    @mock.patch.object(driver.ISCSIDriver, "get_filter_function")
    @mock.patch.object(requests.Session, "request")
    def test_get_volume_stats(
            self, request, get_filter_function, get_goodness_function):
        request.return_value = FakeResponse(200, GET_POOL_RESULT)
        get_filter_function.return_value = None
        get_goodness_function.return_value = None
        stats = self.driver.get_volume_stats(True)
        self.assertEqual('Hitachi', stats['vendor_name'])
        self.assertTrue(stats["pools"][0]['multiattach'])
        self.assertEqual(1, request.call_count)
        self.assertEqual(1, get_filter_function.call_count)
        self.assertEqual(1, get_goodness_function.call_count)

    @mock.patch.object(requests.Session, "request")
    def test_create_volume(self, request):
        request.return_value = FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)
        ret = self.driver.create_volume(fake_volume.fake_volume_obj(self.ctxt))
        self.assertEqual('1', ret['provider_location'])
        self.assertEqual(2, request.call_count)

    @mock.patch.object(requests.Session, "request")
    def test_delete_volume(self, request):
        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)]
        self.driver.delete_volume(TEST_VOLUME[0])
        self.assertEqual(4, request.call_count)

    @mock.patch.object(requests.Session, "request")
    @mock.patch.object(sqlalchemy_api, 'volume_get', side_effect=_volume_get)
    def test_create_snapshot(self, volume_get, request):
        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(200, GET_SNAPSHOTS_RESULT)]
        ret = self.driver.create_snapshot(TEST_SNAPSHOT[0])
        self.assertEqual('1', ret['provider_location'])
        self.assertEqual(4, request.call_count)

    @mock.patch.object(requests.Session, "request")
    def test_delete_snapshot(self, request):
        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)]
        self.driver.delete_snapshot(TEST_SNAPSHOT[0])
        self.assertEqual(4, request.call_count)

    @mock.patch.object(requests.Session, "request")
    def test_create_cloned_volume(self, request):
        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(200, GET_SNAPSHOTS_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)]
        vol = self.driver.create_cloned_volume(TEST_VOLUME[0], TEST_VOLUME[1])
        self.assertEqual('1', vol['provider_location'])
        self.assertEqual(5, request.call_count)

    @mock.patch.object(requests.Session, "request")
    def test_create_volume_from_snapshot(self, request):
        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(200, GET_SNAPSHOTS_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)]
        vol = self.driver.create_volume_from_snapshot(
            TEST_VOLUME[0], TEST_SNAPSHOT[0])
        self.assertEqual('1', vol['provider_location'])
        self.assertEqual(5, request.call_count)

    @mock.patch.object(requests.Session, "request")
    def test_initialize_connection(self, request):
        request.side_effect = [FakeResponse(200, GET_HOST_ISCSIS_RESULT),
                               FakeResponse(200, GET_HOST_GROUP_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)]
        ret = self.driver.initialize_connection(
            TEST_VOLUME[0], DEFAULT_CONNECTOR)
        self.assertEqual('iscsi', ret['driver_volume_type'])
        self.assertEqual(
            '%(ip)s:%(port)s' % {
                'ip': CONFIG_MAP['ipv4Address'],
                'port': CONFIG_MAP['tcpPort'],
            },
            ret['data']['target_portal'])
        self.assertEqual(CONFIG_MAP['target_iscsi_name'],
                         ret['data']['target_iqn'])
        self.assertEqual('CHAP', ret['data']['auth_method'])
        self.assertEqual(CONFIG_MAP['auth_user'], ret['data']['auth_username'])
        self.assertEqual(
            CONFIG_MAP['auth_password'], ret['data']['auth_password'])
        self.assertEqual(1, ret['data']['target_lun'])
        self.assertEqual(3, request.call_count)

    @mock.patch.object(requests.Session, "request")
    def test_initialize_connection_shared_target(self, request):
        """Normal case: A target shared with other systems."""
        request.side_effect = [FakeResponse(200, NOTFOUND_RESULT),
                               FakeResponse(200, GET_HOST_GROUPS_RESULT),
                               FakeResponse(200, GET_HOST_ISCSIS_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)]
        ret = self.driver.initialize_connection(
            TEST_VOLUME[0], DEFAULT_CONNECTOR)
        self.assertEqual('iscsi', ret['driver_volume_type'])
        self.assertEqual(
            '%(ip)s:%(port)s' % {
                'ip': CONFIG_MAP['ipv4Address'],
                'port': CONFIG_MAP['tcpPort'],
            },
            ret['data']['target_portal'])
        self.assertEqual(CONFIG_MAP['target_iscsi_name'],
                         ret['data']['target_iqn'])
        self.assertEqual('CHAP', ret['data']['auth_method'])
        self.assertEqual(CONFIG_MAP['auth_user'], ret['data']['auth_username'])
        self.assertEqual(
            CONFIG_MAP['auth_password'], ret['data']['auth_password'])
        self.assertEqual(1, ret['data']['target_lun'])
        self.assertEqual(4, request.call_count)

    @mock.patch.object(requests.Session, "request")
    def test_terminate_connection(self, request):
        request.side_effect = [FakeResponse(200, GET_HOST_ISCSIS_RESULT),
                               FakeResponse(200, GET_HOST_GROUP_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT_MAPPED),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(200, NOTFOUND_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)]
        self.driver.terminate_connection(TEST_VOLUME[2], DEFAULT_CONNECTOR)
        self.assertEqual(6, request.call_count)

    @mock.patch.object(requests.Session, "request")
    def test_terminate_connection_not_connector(self, request):
        """Normal case: Connector is None."""
        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT_MAPPED),
                               FakeResponse(200, GET_HOST_GROUP_RESULT),
                               FakeResponse(200, GET_HOST_ISCSIS_RESULT),
                               FakeResponse(200, GET_HOST_GROUPS_RESULT),
                               FakeResponse(200, GET_HOST_ISCSIS_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT_MAPPED),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(200, NOTFOUND_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)]
        self.driver.terminate_connection(TEST_VOLUME[2], None)
        self.assertEqual(9, request.call_count)

    @mock.patch.object(requests.Session, "request")
    def test_initialize_connection_snapshot(self, request):
        request.side_effect = [FakeResponse(200, GET_HOST_ISCSIS_RESULT),
                               FakeResponse(200, GET_HOST_GROUP_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)]
        ret = self.driver.initialize_connection_snapshot(
            TEST_SNAPSHOT[0], DEFAULT_CONNECTOR)
        self.assertEqual('iscsi', ret['driver_volume_type'])
        self.assertEqual(
            '%(ip)s:%(port)s' % {
                'ip': CONFIG_MAP['ipv4Address'],
                'port': CONFIG_MAP['tcpPort'],
            },
            ret['data']['target_portal'])
        self.assertEqual(CONFIG_MAP['target_iscsi_name'],
                         ret['data']['target_iqn'])
        self.assertEqual('CHAP', ret['data']['auth_method'])
        self.assertEqual(CONFIG_MAP['auth_user'], ret['data']['auth_username'])
        self.assertEqual(
            CONFIG_MAP['auth_password'], ret['data']['auth_password'])
        self.assertEqual(1, ret['data']['target_lun'])
        self.assertEqual(3, request.call_count)

    @mock.patch.object(requests.Session, "request")
    def test_terminate_connection_snapshot(self, request):
        request.side_effect = [FakeResponse(200, GET_HOST_ISCSIS_RESULT),
                               FakeResponse(200, GET_HOST_GROUP_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT_MAPPED),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(200, NOTFOUND_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)]
        self.driver.terminate_connection_snapshot(
            TEST_SNAPSHOT[0], DEFAULT_CONNECTOR)
        self.assertEqual(6, request.call_count)

    @mock.patch.object(requests.Session, "request")
    def test_manage_existing(self, request):
        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)]
        ret = self.driver.manage_existing(
            TEST_VOLUME[0], self.test_existing_ref)
        self.assertEqual('1', ret['provider_location'])
        self.assertEqual(2, request.call_count)

    @mock.patch.object(requests.Session, "request")
    def test_manage_existing_name(self, request):
        request.side_effect = [FakeResponse(200, GET_LDEVS_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)]
        ret = self.driver.manage_existing(
            TEST_VOLUME[0], self.test_existing_ref_name)
        self.assertEqual('1', ret['provider_location'])
        self.assertEqual(3, request.call_count)

    @mock.patch.object(requests.Session, "request")
    def test_manage_existing_get_size(self, request):
        request.return_value = FakeResponse(200, GET_LDEV_RESULT)
        self.driver.manage_existing_get_size(
            TEST_VOLUME[0], self.test_existing_ref)
        self.assertEqual(1, request.call_count)

    @mock.patch.object(requests.Session, "request")
    def test_manage_existing_get_size_name(self, request):
        request.side_effect = [FakeResponse(200, GET_LDEVS_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT)]
        self.driver.manage_existing_get_size(
            TEST_VOLUME[0], self.test_existing_ref_name)
        self.assertEqual(2, request.call_count)

    @mock.patch.object(requests.Session, "request")
    def test_unmanage(self, request):
        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT)]
        self.driver.unmanage(TEST_VOLUME[0])
        self.assertEqual(2, request.call_count)

    @mock.patch.object(requests.Session, "request")
    def test_copy_image_to_volume(self, request):
        image_service = 'fake_image_service'
        image_id = 'fake_image_id'
        request.return_value = FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)
        with mock.patch.object(driver.VolumeDriver, 'copy_image_to_volume') \
                as mock_copy_image:
            self.driver.copy_image_to_volume(
                self.ctxt, TEST_VOLUME[0], image_service, image_id)
        mock_copy_image.assert_called_with(
            self.ctxt, TEST_VOLUME[0], image_service, image_id)
        self.assertEqual(1, request.call_count)

    @mock.patch.object(requests.Session, "request")
    def test_update_migrated_volume(self, request):
        request.return_value = FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)
        self.assertRaises(
            NotImplementedError,
            self.driver.update_migrated_volume,
            self.ctxt,
            TEST_VOLUME[0],
            TEST_VOLUME[1],
            "available")
        self.assertEqual(1, request.call_count)

    def test_unmanage_snapshot(self):
        """The driver don't support unmange_snapshot."""
        self.assertRaises(
            NotImplementedError,
            self.driver.unmanage_snapshot,
            TEST_SNAPSHOT[0])

    def test_retype(self):
        new_specs = {'hbsd:test': 'test'}
        new_type_ref = volume_types.create(self.ctxt, 'new', new_specs)
        diff = {}
        host = {}
        ret = self.driver.retype(
            self.ctxt, TEST_VOLUME[0], new_type_ref, diff, host)
        self.assertFalse(ret)

    def test_backup_use_temp_snapshot(self):
        self.assertTrue(self.driver.backup_use_temp_snapshot())

    @mock.patch.object(requests.Session, "request")
    def test_revert_to_snapshot(self, request):
        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT_PAIR),
                               FakeResponse(200, GET_SNAPSHOTS_RESULT),
                               FakeResponse(200, GET_SNAPSHOTS_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(200, GET_SNAPSHOTS_RESULT)]
        self.driver.revert_to_snapshot(
            self.ctxt, TEST_VOLUME[0], TEST_SNAPSHOT[0])
        self.assertEqual(5, request.call_count)

    def test_create_group(self):
        ret = self.driver.create_group(self.ctxt, TEST_GROUP[0])
        self.assertIsNone(ret)

    @mock.patch.object(requests.Session, "request")
    def test_delete_group(self, request):
        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)]
        ret = self.driver.delete_group(
            self.ctxt, TEST_GROUP[0], [TEST_VOLUME[0]])
        self.assertEqual(4, request.call_count)
        actual = (
            {'status': TEST_GROUP[0]['status']},
            [{'id': TEST_VOLUME[0]['id'], 'status': 'deleted'}]
        )
        self.assertTupleEqual(actual, ret)

    @mock.patch.object(requests.Session, "request")
    def test_create_group_from_src_volume(self, request):
        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(200, GET_SNAPSHOTS_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)]
        ret = self.driver.create_group_from_src(
            self.ctxt, TEST_GROUP[1], [TEST_VOLUME[1]],
            source_group=TEST_GROUP[0], source_vols=[TEST_VOLUME[0]]
        )
        self.assertEqual(5, request.call_count)
        actual = (
            None, [{'id': TEST_VOLUME[1]['id'], 'provider_location': '1'}])
        self.assertTupleEqual(actual, ret)

    @mock.patch.object(requests.Session, "request")
    def test_create_group_from_src_snapshot(self, request):
        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(200, GET_SNAPSHOTS_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)]
        ret = self.driver.create_group_from_src(
            self.ctxt, TEST_GROUP[0], [TEST_VOLUME[0]],
            group_snapshot=TEST_GROUP_SNAP[0], snapshots=[TEST_SNAPSHOT[0]]
        )
        self.assertEqual(5, request.call_count)
        actual = (
            None, [{'id': TEST_VOLUME[0]['id'], 'provider_location': '1'}])
        self.assertTupleEqual(actual, ret)

    def test_create_group_from_src_volume_error(self):
        self.assertRaises(
            hbsd_utils.HBSDError, self.driver.create_group_from_src,
            self.ctxt, TEST_GROUP[1], [TEST_VOLUME[1]],
            source_group=TEST_GROUP[0], source_vols=[TEST_VOLUME[3]]
        )

    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type')
    def test_update_group(self, is_group_a_cg_snapshot_type):
        is_group_a_cg_snapshot_type.return_value = False
        ret = self.driver.update_group(
            self.ctxt, TEST_GROUP[0], add_volumes=[TEST_VOLUME[0]])
        self.assertTupleEqual((None, None, None), ret)

    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type')
    def test_update_group_error(self, is_group_a_cg_snapshot_type):
        is_group_a_cg_snapshot_type.return_value = True
        self.assertRaises(
            hbsd_utils.HBSDError, self.driver.update_group,
            self.ctxt, TEST_GROUP[0], add_volumes=[TEST_VOLUME[3]],
            remove_volumes=[TEST_VOLUME[0]]
        )

    @mock.patch.object(requests.Session, "request")
    @mock.patch.object(sqlalchemy_api, 'volume_get', side_effect=_volume_get)
    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type')
    def test_create_group_snapshot_non_cg(
            self, is_group_a_cg_snapshot_type, volume_get, request):
        is_group_a_cg_snapshot_type.return_value = False
        request.side_effect = [FakeResponse(200, GET_LDEV_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(200, GET_SNAPSHOTS_RESULT)]
        ret = self.driver.create_group_snapshot(
            self.ctxt, TEST_GROUP_SNAP[0], [TEST_SNAPSHOT[0]]
        )
        self.assertEqual(4, request.call_count)
        actual = (
            {'status': 'available'},
            [{'id': TEST_SNAPSHOT[0]['id'],
              'provider_location': '1',
              'status': 'available'}]
        )
        self.assertTupleEqual(actual, ret)

    @mock.patch.object(requests.Session, "request")
    @mock.patch.object(sqlalchemy_api, 'volume_get', side_effect=_volume_get)
    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type')
    def test_create_group_snapshot_cg(
            self, is_group_a_cg_snapshot_type, volume_get, request):
        is_group_a_cg_snapshot_type.return_value = True
        request.side_effect = [FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(200, GET_SNAPSHOTS_RESULT_PAIR),
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT),
                               FakeResponse(200, GET_SNAPSHOTS_RESULT)]
        ret = self.driver.create_group_snapshot(
            self.ctxt, TEST_GROUP_SNAP[0], [TEST_SNAPSHOT[0]]
        )
        self.assertEqual(5, request.call_count)
        actual = (
            None,
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
                               FakeResponse(202, COMPLETED_SUCCEEDED_RESULT)]
        ret = self.driver.delete_group_snapshot(
            self.ctxt, TEST_GROUP_SNAP[0], [TEST_SNAPSHOT[0]])
        self.assertEqual(10, request.call_count)
        actual = (
            {'status': TEST_GROUP_SNAP[0]['status']},
            [{'id': TEST_SNAPSHOT[0]['id'], 'status': 'deleted'}]
        )
        self.assertTupleEqual(actual, ret)
