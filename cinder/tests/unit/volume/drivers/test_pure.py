# Copyright (c) 2014 Pure Storage, Inc.
# All Rights Reserved.
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

from copy import deepcopy
import sys

import ddt
import mock
from oslo_utils import units
from six.moves import http_client

from cinder import exception
from cinder import test
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_group
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume


def fake_retry(exceptions, interval=1, retries=3, backoff_rate=2):
    def _decorator(f):
        return f
    return _decorator

patch_retry = mock.patch('cinder.utils.retry', fake_retry)
patch_retry.start()
sys.modules['purestorage'] = mock.Mock()
from cinder.volume.drivers import pure

# Only mock utils.retry for cinder.volume.drivers.pure import
patch_retry.stop()

DRIVER_PATH = "cinder.volume.drivers.pure"
BASE_DRIVER_OBJ = DRIVER_PATH + ".PureBaseVolumeDriver"
ISCSI_DRIVER_OBJ = DRIVER_PATH + ".PureISCSIDriver"
FC_DRIVER_OBJ = DRIVER_PATH + ".PureFCDriver"
ARRAY_OBJ = DRIVER_PATH + ".FlashArray"

GET_ARRAY_PRIMARY = {"version": "99.9.9",
                     "revision": "201411230504+8a400f7",
                     "array_name": "pure_target1",
                     "id": "primary_array_id"}

GET_ARRAY_SECONDARY = {"version": "99.9.9",
                       "revision": "201411230504+8a400f7",
                       "array_name": "pure_target2",
                       "id": "secondary_array_id"}

REPLICATION_TARGET_TOKEN = "12345678-abcd-1234-abcd-1234567890ab"
REPLICATION_PROTECTION_GROUP = "cinder-group"
REPLICATION_INTERVAL_IN_SEC = 3600
REPLICATION_RETENTION_SHORT_TERM = 14400
REPLICATION_RETENTION_LONG_TERM = 6
REPLICATION_RETENTION_LONG_TERM_PER_DAY = 3

PRIMARY_MANAGEMENT_IP = GET_ARRAY_PRIMARY["array_name"]
API_TOKEN = "12345678-abcd-1234-abcd-1234567890ab"
VOLUME_BACKEND_NAME = "Pure_iSCSI"
ISCSI_PORT_NAMES = ["ct0.eth2", "ct0.eth3", "ct1.eth2", "ct1.eth3"]
FC_PORT_NAMES = ["ct0.fc2", "ct0.fc3", "ct1.fc2", "ct1.fc3"]
ISCSI_IPS = ["10.0.0." + str(i + 1) for i in range(len(ISCSI_PORT_NAMES))]
FC_WWNS = ["21000024ff59fe9" + str(i + 1) for i in range(len(FC_PORT_NAMES))]
HOSTNAME = "computenode1"
PURE_HOST_NAME = pure.PureBaseVolumeDriver._generate_purity_host_name(HOSTNAME)
PURE_HOST = {
    "name": PURE_HOST_NAME,
    "hgroup": None,
    "iqn": [],
    "wwn": [],
}
REST_VERSION = "1.2"
VOLUME_ID = "abcdabcd-1234-abcd-1234-abcdeffedcba"
VOLUME_TYPE_ID = "357aa1f1-4f9c-4f10-acec-626af66425ba"
VOLUME = {
    "name": "volume-" + VOLUME_ID,
    "id": VOLUME_ID,
    "display_name": "fake_volume",
    "size": 2,
    "host": "irrelevant",
    "volume_type": None,
    "volume_type_id": VOLUME_TYPE_ID,
    "replication_status": None,
    "consistencygroup_id": None,
    "provider_location": GET_ARRAY_PRIMARY["id"],
    "group_id": None,
}
VOLUME_PURITY_NAME = VOLUME['name'] + '-cinder'
VOLUME_WITH_CGROUP = VOLUME.copy()
VOLUME_WITH_CGROUP['group_id'] = "4a2f7e3a-312a-40c5-96a8-536b8a0fe074"
VOLUME_WITH_CGROUP['consistencygroup_id'] = \
    "4a2f7e3a-312a-40c5-96a8-536b8a0fe074"
SRC_VOL_ID = "dc7a294d-5964-4379-a15f-ce5554734efc"
SRC_VOL = {
    "name": "volume-" + SRC_VOL_ID,
    "id": SRC_VOL_ID,
    "display_name": 'fake_src',
    "size": 2,
    "host": "irrelevant",
    "volume_type": None,
    "volume_type_id": None,
    "consistencygroup_id": None,
    "group_id": None,
}
SNAPSHOT_ID = "04fe2f9a-d0c4-4564-a30d-693cc3657b47"
SNAPSHOT = {
    "name": "snapshot-" + SNAPSHOT_ID,
    "id": SNAPSHOT_ID,
    "volume_id": SRC_VOL_ID,
    "volume_name": "volume-" + SRC_VOL_ID,
    "volume_size": 2,
    "display_name": "fake_snapshot",
    "cgsnapshot_id": None,
    "cgsnapshot": None,
    "group_snapshot_id": None,
    "group_snapshot": None,
}
SNAPSHOT_PURITY_NAME = SRC_VOL["name"] + '-cinder.' + SNAPSHOT["name"]
SNAPSHOT_WITH_CGROUP = SNAPSHOT.copy()
SNAPSHOT_WITH_CGROUP['group_snapshot'] = {
    "group_id": "4a2f7e3a-312a-40c5-96a8-536b8a0fe044",
}
INITIATOR_IQN = "iqn.1993-08.org.debian:01:222"
INITIATOR_WWN = "5001500150015081abc"
ISCSI_CONNECTOR = {"initiator": INITIATOR_IQN, "host": HOSTNAME}
FC_CONNECTOR = {"wwpns": {INITIATOR_WWN}, "host": HOSTNAME}
TARGET_IQN = "iqn.2010-06.com.purestorage:flasharray.12345abc"
TARGET_WWN = "21000024ff59fe94"
TARGET_PORT = "3260"
INITIATOR_TARGET_MAP =\
    {
        # _build_initiator_target_map() calls list(set()) on the list,
        # we must also call list(set()) to get the exact same order
        '5001500150015081abc': list(set(FC_WWNS)),
    }
DEVICE_MAPPING =\
    {
        "fabric": {'initiator_port_wwn_list': {INITIATOR_WWN},
                   'target_port_wwn_list': FC_WWNS
                   },
    }

ISCSI_PORTS = [{"name": name,
                "iqn": TARGET_IQN,
                "portal": ip + ":" + TARGET_PORT,
                "wwn": None,
                } for name, ip in zip(ISCSI_PORT_NAMES, ISCSI_IPS)]
FC_PORTS = [{"name": name,
             "iqn": None,
             "portal": None,
             "wwn": wwn,
             } for name, wwn in zip(FC_PORT_NAMES, FC_WWNS)]
NON_ISCSI_PORT = {
    "name": "ct0.fc1",
    "iqn": None,
    "portal": None,
    "wwn": "5001500150015081",
}
PORTS_WITH = ISCSI_PORTS + [NON_ISCSI_PORT]
PORTS_WITHOUT = [NON_ISCSI_PORT]
VOLUME_CONNECTIONS = [
    {"host": "h1", "name": VOLUME["name"] + "-cinder"},
    {"host": "h2", "name": VOLUME["name"] + "-cinder"},
]
TOTAL_CAPACITY = 50.0
USED_SPACE = 32.1
PROVISIONED_CAPACITY = 70.0
DEFAULT_OVER_SUBSCRIPTION = 20
SPACE_INFO = {
    "capacity": TOTAL_CAPACITY * units.Gi,
    "total": USED_SPACE * units.Gi,
}
SPACE_INFO_EMPTY = {
    "capacity": TOTAL_CAPACITY * units.Gi,
    "total": 0,
}

PERF_INFO = {
    'writes_per_sec': 318,
    'usec_per_write_op': 255,
    'output_per_sec': 234240,
    'reads_per_sec': 15,
    'input_per_sec': 2827943,
    'time': '2015-12-17T21:50:55Z',
    'usec_per_read_op': 192,
    'queue_depth': 4,
}
PERF_INFO_RAW = [PERF_INFO]

ISCSI_CONNECTION_INFO = {
    "driver_volume_type": "iscsi",
    "data": {
        "target_discovered": False,
        "discard": True,
        "target_luns": [1, 1, 1, 1],
        "target_iqns": [TARGET_IQN, TARGET_IQN, TARGET_IQN, TARGET_IQN],
        "target_portals": [ISCSI_IPS[0] + ":" + TARGET_PORT,
                           ISCSI_IPS[1] + ":" + TARGET_PORT,
                           ISCSI_IPS[2] + ":" + TARGET_PORT,
                           ISCSI_IPS[3] + ":" + TARGET_PORT],
    },
}
FC_CONNECTION_INFO = {
    "driver_volume_type": "fibre_channel",
    "data": {
        "target_wwn": FC_WWNS,
        "target_lun": 1,
        "target_discovered": True,
        "initiator_target_map": INITIATOR_TARGET_MAP,
        "discard": True,
    },
}
PURE_SNAPSHOT = {
    "created": "2015-05-27T17:34:33Z",
    "name": "vol1.snap1",
    "serial": "8343DFDE2DAFBE40000115E4",
    "size": 3221225472,
    "source": "vol1"
}
PURE_PGROUP = {
    "hgroups": None,
    "hosts": None,
    "name": "pg1",
    "source": "pure01",
    "targets": None,
    "volumes": ["v1"]
}

PGROUP_ON_TARGET_NOT_ALLOWED = {
    "name": "array1:replicated_pgroup",
    "hgroups": None,
    "source": "array1",
    "hosts": None,
    "volumes": ["array1:replicated_volume"],
    "time_remaining": None,
    "targets": [{"name": "array2",
                 "allowed": False}]}
PGROUP_ON_TARGET_ALLOWED = {
    "name": "array1:replicated_pgroup",
    "hgroups": None,
    "source": "array1",
    "hosts": None,
    "volumes": ["array1:replicated_volume"],
    "time_remaining": None,
    "targets": [{"name": "array2",
                 "allowed": True}]}
CONNECTED_ARRAY = {
    "id": "6b1a7ce3-da61-0d86-65a7-9772cd259fef",
    "version": "99.9.9",
    "connected": True,
    "management_address": "10.42.10.229",
    "replication_address": "192.168.10.229",
    "type": ["replication"],
    "array_name": "3rd-pure-generic2"}
REPLICATED_PGSNAPS = [
    {
        "name": "array1:cinder-repl-pg.3",
        "created": "2014-12-04T22:59:38Z",
        "started": "2014-12-04T22:59:38Z",
        "completed": "2014-12-04T22:59:39Z",
        "source": "array1:cinder-repl-pg",
        "logical_data_transferred": 0,
        "progress": 1.0,
        "data_transferred": 318
    },
    {
        "name": "array1:cinder-repl-pg.2",
        "created": "2014-12-04T21:59:38Z",
        "started": "2014-12-04T21:59:38Z",
        "completed": "2014-12-04T21:59:39Z",
        "source": "array1:cinder-repl-pg",
        "logical_data_transferred": 0,
        "progress": 1.0,
        "data_transferred": 318
    },
    {
        "name": "array1:cinder-repl-pg.1",
        "created": "2014-12-04T20:59:38Z",
        "started": "2014-12-04T20:59:38Z",
        "completed": "2014-12-04T20:59:39Z",
        "source": "array1:cinder-repl-pg",
        "logical_data_transferred": 0,
        "progress": 1.0,
        "data_transferred": 318
    }]
REPLICATED_VOLUME_OBJS = [
    fake_volume.fake_volume_obj(None, id=fake.VOLUME_ID),
    fake_volume.fake_volume_obj(None, id=fake.VOLUME2_ID),
    fake_volume.fake_volume_obj(None, id=fake.VOLUME3_ID),
]
REPLICATED_VOLUME_SNAPS = [
    {
        "source": "array1:volume-%s-cinder" % fake.VOLUME_ID,
        "serial": "BBA481C01639104E0001D5F7",
        "created": "2014-12-04T22:59:38Z",
        "name": "array1:cinder-repl-pg.2.volume-%s-cinder" % fake.VOLUME_ID,
        "size": 1048576
    },
    {
        "source": "array1:volume-%s-cinder" % fake.VOLUME2_ID,
        "serial": "BBA481C01639104E0001D5F8",
        "created": "2014-12-04T22:59:38Z",
        "name": "array1:cinder-repl-pg.2.volume-%s-cinder" % fake.VOLUME2_ID,
        "size": 1048576
    },
    {
        "source": "array1:volume-%s-cinder" % fake.VOLUME3_ID,
        "serial": "BBA481C01639104E0001D5F9",
        "created": "2014-12-04T22:59:38Z",
        "name": "array1:cinder-repl-pg.2.volume-%s-cinder" % fake.VOLUME3_ID,
        "size": 1048576
    }
]

NON_REPLICATED_VOL_TYPE = {"is_public": True,
                           "extra_specs": {},
                           "name": "volume_type_1",
                           "id": VOLUME_TYPE_ID}
REPLICATED_VOL_TYPE = {"is_public": True,
                       "extra_specs":
                       {pure.EXTRA_SPECS_REPL_ENABLED:
                        "<is> True"},
                       "name": "volume_type_2",
                       "id": VOLUME_TYPE_ID}
MANAGEABLE_PURE_VOLS = [
    {
        'name': 'myVol1',
        'serial': '8E9C7E588B16C1EA00048CCA',
        'size': 3221225472,
        'created': '2016-08-05T17:26:34Z',
        'source': None,
    },
    {
        'name': 'myVol2',
        'serial': '8E9C7E588B16C1EA00048CCB',
        'size': 3221225472,
        'created': '2016-08-05T17:26:34Z',
        'source': None,
    },
    {
        'name': 'myVol3',
        'serial': '8E9C7E588B16C1EA00048CCD',
        'size': 3221225472,
        'created': '2016-08-05T17:26:34Z',
        'source': None,
    }
]
MANAGEABLE_PURE_VOL_REFS = [
    {
        'reference': {'name': 'myVol1'},
        'size': 3,
        'safe_to_manage': True,
        'reason_not_safe': None,
        'cinder_id': None,
        'extra_info': None,
    },
    {
        'reference': {'name': 'myVol2'},
        'size': 3,
        'safe_to_manage': True,
        'reason_not_safe': None,
        'cinder_id': None,
        'extra_info': None,
    },
    {
        'reference': {'name': 'myVol3'},
        'size': 3,
        'safe_to_manage': True,
        'reason_not_safe': None,
        'cinder_id': None,
        'extra_info': None,
    }
]

MANAGEABLE_PURE_SNAPS = [
    {
        'name': 'volume-fd33de6e-56f6-452d-a7b6-451c11089a9f-cinder.snap1',
        'serial': '8E9C7E588B16C1EA00048CCA',
        'size': 3221225472,
        'created': '2016-08-05T17:26:34Z',
        'source': 'volume-fd33de6e-56f6-452d-a7b6-451c11089a9f-cinder',
    },
    {
        'name': 'volume-fd33de6e-56f6-452d-a7b6-451c11089a9f-cinder.snap2',
        'serial': '8E9C7E588B16C1EA00048CCB',
        'size': 4221225472,
        'created': '2016-08-05T17:26:34Z',
        'source': 'volume-fd33de6e-56f6-452d-a7b6-451c11089a9f-cinder',
    },
    {
        'name': 'volume-fd33de6e-56f6-452d-a7b6-451c11089a9f-cinder.snap3',
        'serial': '8E9C7E588B16C1EA00048CCD',
        'size': 5221225472,
        'created': '2016-08-05T17:26:34Z',
        'source': 'volume-fd33de6e-56f6-452d-a7b6-451c11089a9f-cinder',
    }
]
MANAGEABLE_PURE_SNAP_REFS = [
    {
        'reference': {'name': MANAGEABLE_PURE_SNAPS[0]['name']},
        'size': 3,
        'safe_to_manage': True,
        'reason_not_safe': None,
        'cinder_id': None,
        'extra_info': None,
        'source_reference': {'name': MANAGEABLE_PURE_SNAPS[0]['source']},
    },
    {
        'reference': {'name': MANAGEABLE_PURE_SNAPS[1]['name']},
        'size': 4,
        'safe_to_manage': True,
        'reason_not_safe': None,
        'cinder_id': None,
        'extra_info': None,
        'source_reference': {'name': MANAGEABLE_PURE_SNAPS[1]['source']},
    },
    {
        'reference': {'name': MANAGEABLE_PURE_SNAPS[2]['name']},
        'size': 5,
        'safe_to_manage': True,
        'reason_not_safe': None,
        'cinder_id': None,
        'extra_info': None,
        'source_reference': {'name': MANAGEABLE_PURE_SNAPS[2]['source']},
    }
]


class FakePureStorageHTTPError(Exception):
    def __init__(self, target=None, rest_version=None, code=None,
                 headers=None, text=None):
        self.target = target
        self.rest_version = rest_version
        self.code = code
        self.headers = headers
        self.text = text


class PureDriverTestCase(test.TestCase):
    def setUp(self):
        super(PureDriverTestCase, self).setUp()
        self.mock_config = mock.Mock()
        self.mock_config.san_ip = PRIMARY_MANAGEMENT_IP
        self.mock_config.pure_api_token = API_TOKEN
        self.mock_config.volume_backend_name = VOLUME_BACKEND_NAME
        self.mock_config.safe_get.return_value = None
        self.mock_config.pure_eradicate_on_delete = False
        self.mock_config.driver_ssl_cert_verify = False
        self.mock_config.driver_ssl_cert_path = None
        self.array = mock.Mock()
        self.array.get.return_value = GET_ARRAY_PRIMARY
        self.array.array_name = GET_ARRAY_PRIMARY["array_name"]
        self.array.array_id = GET_ARRAY_PRIMARY["id"]
        self.array2 = mock.Mock()
        self.array2.array_name = GET_ARRAY_SECONDARY["array_name"]
        self.array2.array_id = GET_ARRAY_SECONDARY["id"]
        self.array2.get.return_value = GET_ARRAY_SECONDARY
        self.purestorage_module = pure.purestorage
        self.purestorage_module.VERSION = '1.4.0'
        self.purestorage_module.PureHTTPError = FakePureStorageHTTPError

    def fake_get_array(*args, **kwargs):
        if 'action' in kwargs and kwargs['action'] is 'monitor':
            return PERF_INFO_RAW

        if 'space' in kwargs and kwargs['space'] is True:
            return SPACE_INFO

    def assert_error_propagates(self, mocks, func, *args, **kwargs):
        """Assert that errors from mocks propagate to func.

        Fail if exceptions raised by mocks are not seen when calling
        func(*args, **kwargs). Ensure that we are really seeing exceptions
        from the mocks by failing if just running func(*args, **kargs) raises
        an exception itself.
        """
        func(*args, **kwargs)
        for mock_func in mocks:
            original_side_effect = mock_func.side_effect
            mock_func.side_effect = [exception.PureDriverException(
                reason='reason')]
            self.assertRaises(exception.PureDriverException,
                              func, *args, **kwargs)
            mock_func.side_effect = original_side_effect

    @mock.patch('platform.platform')
    def test_for_user_agent(self, mock_platform):
        mock_platform.return_value = 'MyFavoritePlatform'
        driver = pure.PureBaseVolumeDriver(configuration=self.mock_config)
        expected_agent = "OpenStack Cinder %s/%s (MyFavoritePlatform)" % (
            driver.__class__.__name__,
            driver.VERSION
        )
        self.assertEqual(expected_agent, driver._user_agent)


class PureBaseSharedDriverTestCase(PureDriverTestCase):
    def setUp(self):
        super(PureBaseSharedDriverTestCase, self).setUp()
        self.driver = pure.PureBaseVolumeDriver(configuration=self.mock_config)
        self.driver._array = self.array
        self.array.get_rest_version.return_value = '1.4'
        self.purestorage_module.FlashArray.side_effect = None
        self.array2.get_rest_version.return_value = '1.4'

    def tearDown(self):
        super(PureBaseSharedDriverTestCase, self).tearDown()


@ddt.ddt
class PureBaseVolumeDriverTestCase(PureBaseSharedDriverTestCase):
    def _setup_mocks_for_replication(self):
        # Mock config values
        self.mock_config.pure_replica_interval_default = (
            REPLICATION_INTERVAL_IN_SEC)
        self.mock_config.pure_replica_retention_short_term_default = (
            REPLICATION_RETENTION_SHORT_TERM)
        self.mock_config.pure_replica_retention_long_term_default = (
            REPLICATION_RETENTION_LONG_TERM)
        self.mock_config.pure_replica_retention_long_term_default = (
            REPLICATION_RETENTION_LONG_TERM_PER_DAY)
        self.mock_config.safe_get.return_value = [
            {"backend_id": self.driver._array.array_id,
             "managed_backend_name": None,
             "san_ip": "1.2.3.4",
             "api_token": "abc123"}]

    @mock.patch(BASE_DRIVER_OBJ + '._generate_replication_retention')
    @mock.patch(BASE_DRIVER_OBJ + '._setup_replicated_pgroups')
    def test_parse_replication_configs_single_target(
            self,
            mock_setup_repl_pgroups,
            mock_generate_replication_retention):
        retention = mock.MagicMock()
        mock_generate_replication_retention.return_value = retention
        mock_setup_repl_pgroups.return_value = None

        # Test single array configured
        self.mock_config.safe_get.return_value = [
            {"backend_id": self.driver._array.id,
             "managed_backend_name": None,
             "san_ip": "1.2.3.4",
             "api_token": "abc123"}]
        self.purestorage_module.FlashArray.return_value = self.array
        self.driver.parse_replication_configs()
        self.assertEqual(1, len(self.driver._replication_target_arrays))
        self.assertEqual(self.array, self.driver._replication_target_arrays[0])
        only_target_array = self.driver._replication_target_arrays[0]
        self.assertEqual(self.driver._array.id,
                         only_target_array._backend_id)

    @mock.patch(BASE_DRIVER_OBJ + '._generate_replication_retention')
    @mock.patch(BASE_DRIVER_OBJ + '._setup_replicated_pgroups')
    def test_parse_replication_configs_multiple_target(
            self,
            mock_setup_repl_pgroups,
            mock_generate_replication_retention):

        retention = mock.MagicMock()
        mock_generate_replication_retention.return_value = retention
        mock_setup_repl_pgroups.return_value = None

        # Test multiple arrays configured
        self.mock_config.safe_get.return_value = [
            {"backend_id": GET_ARRAY_PRIMARY["id"],
             "managed_backend_name": None,
             "san_ip": "1.2.3.4",
             "api_token": "abc123"},
            {"backend_id": GET_ARRAY_SECONDARY["id"],
             "managed_backend_name": None,
             "san_ip": "1.2.3.5",
             "api_token": "abc124"}]
        self.purestorage_module.FlashArray.side_effect = \
            [self.array, self.array2]
        self.driver.parse_replication_configs()
        self.assertEqual(2, len(self.driver._replication_target_arrays))
        self.assertEqual(self.array, self.driver._replication_target_arrays[0])
        first_target_array = self.driver._replication_target_arrays[0]
        self.assertEqual(GET_ARRAY_PRIMARY["id"],
                         first_target_array._backend_id)
        self.assertEqual(
            self.array2, self.driver._replication_target_arrays[1])
        second_target_array = self.driver._replication_target_arrays[1]
        self.assertEqual(GET_ARRAY_SECONDARY["id"],
                         second_target_array._backend_id)

    @mock.patch(BASE_DRIVER_OBJ + '._generate_replication_retention')
    @mock.patch(BASE_DRIVER_OBJ + '._setup_replicated_pgroups')
    @mock.patch('cinder.volume.volume_types.get_volume_type')
    def test_do_setup_replicated(self, mock_get_volume_type,
                                 mock_setup_repl_pgroups,
                                 mock_generate_replication_retention):
        retention = mock.MagicMock()
        mock_generate_replication_retention.return_value = retention
        mock_get_volume_type.return_value = REPLICATED_VOL_TYPE
        self._setup_mocks_for_replication()
        self.array2.get.return_value = GET_ARRAY_SECONDARY
        self.array.get.return_value = GET_ARRAY_PRIMARY
        self.purestorage_module.FlashArray.side_effect = [self.array,
                                                          self.array2]
        self.driver.do_setup(None)
        self.assertEqual(self.array, self.driver._array)
        self.assertEqual(1, len(self.driver._replication_target_arrays))
        self.assertEqual(self.array2,
                         self.driver._replication_target_arrays[0])
        calls = [
            mock.call(self.array, [self.array2], 'cinder-group',
                      REPLICATION_INTERVAL_IN_SEC, retention)
        ]
        mock_setup_repl_pgroups.assert_has_calls(calls)

    def test_generate_purity_host_name(self):
        result = self.driver._generate_purity_host_name(
            "really-long-string-thats-a-bit-too-long")
        self.assertTrue(result.startswith("really-long-string-that-"))
        self.assertTrue(result.endswith("-cinder"))
        self.assertEqual(63, len(result))
        self.assertTrue(pure.GENERATED_NAME.match(result))
        result = self.driver._generate_purity_host_name("!@#$%^-invalid&*")
        self.assertTrue(result.startswith("invalid---"))
        self.assertTrue(result.endswith("-cinder"))
        self.assertEqual(49, len(result))
        self.assertTrue(pure.GENERATED_NAME.match(result))

    @mock.patch(BASE_DRIVER_OBJ + "._add_to_group_if_needed")
    @mock.patch(BASE_DRIVER_OBJ + "._is_volume_replicated_type", autospec=True)
    def test_create_volume(self, mock_is_replicated_type, mock_add_to_group):
        mock_is_replicated_type.return_value = False
        self.driver.create_volume(VOLUME)
        vol_name = VOLUME["name"] + "-cinder"
        self.array.create_volume.assert_called_with(
            vol_name, 2 * units.Gi)
        mock_add_to_group.assert_called_once_with(VOLUME,
                                                  vol_name)
        self.assert_error_propagates([self.array.create_volume],
                                     self.driver.create_volume, VOLUME)

    @mock.patch(BASE_DRIVER_OBJ + "._add_to_group_if_needed")
    @mock.patch(BASE_DRIVER_OBJ + "._is_volume_replicated_type", autospec=True)
    def test_create_volume_from_snapshot(self, mock_is_replicated_type,
                                         mock_add_to_group):
        vol_name = VOLUME["name"] + "-cinder"
        snap_name = SNAPSHOT["volume_name"] + "-cinder." + SNAPSHOT["name"]
        mock_is_replicated_type.return_value = False

        # Branch where extend unneeded
        self.driver.create_volume_from_snapshot(VOLUME, SNAPSHOT)
        self.array.copy_volume.assert_called_with(snap_name, vol_name)
        self.assertFalse(self.array.extend_volume.called)
        mock_add_to_group.assert_called_once_with(VOLUME,
                                                  vol_name)
        self.assert_error_propagates(
            [self.array.copy_volume],
            self.driver.create_volume_from_snapshot, VOLUME, SNAPSHOT)
        self.assertFalse(self.array.extend_volume.called)

    @mock.patch(BASE_DRIVER_OBJ + "._add_to_group_if_needed")
    @mock.patch(BASE_DRIVER_OBJ + "._is_volume_replicated_type",
                autospec=True)
    def test_create_volume_from_snapshot_with_extend(self,
                                                     mock_is_replicated_type,
                                                     mock_add_to_group):
        vol_name = VOLUME["name"] + "-cinder"
        snap_name = SNAPSHOT["volume_name"] + "-cinder." + SNAPSHOT["name"]
        mock_is_replicated_type.return_value = False

        # Branch where extend needed
        src = deepcopy(SNAPSHOT)
        src["volume_size"] = 1  # resize so smaller than VOLUME
        self.driver.create_volume_from_snapshot(VOLUME, src)
        expected = [mock.call.copy_volume(snap_name, vol_name),
                    mock.call.extend_volume(vol_name, 2 * units.Gi)]
        self.array.assert_has_calls(expected)
        mock_add_to_group.assert_called_once_with(VOLUME,
                                                  vol_name)

    @mock.patch(BASE_DRIVER_OBJ + "._get_snap_name")
    def test_create_volume_from_snapshot_cant_get_name(self, mock_get_name):
        mock_get_name.return_value = None
        self.assertRaises(exception.PureDriverException,
                          self.driver.create_volume_from_snapshot,
                          VOLUME, SNAPSHOT)

    @mock.patch(BASE_DRIVER_OBJ + "._get_pgroup_snap_name_from_snapshot")
    def test_create_volume_from_cgsnapshot_cant_get_name(self, mock_get_name):
        mock_get_name.return_value = None
        self.assertRaises(exception.PureDriverException,
                          self.driver.create_volume_from_snapshot,
                          VOLUME, SNAPSHOT_WITH_CGROUP)

    @mock.patch(BASE_DRIVER_OBJ + "._add_to_group_if_needed")
    @mock.patch(BASE_DRIVER_OBJ + "._extend_if_needed", autospec=True)
    @mock.patch(BASE_DRIVER_OBJ + "._get_pgroup_snap_name_from_snapshot")
    @mock.patch(BASE_DRIVER_OBJ + "._is_volume_replicated_type", autospec=True)
    def test_create_volume_from_cgsnapshot(self, mock_is_replicated_type,
                                           mock_get_snap_name,
                                           mock_extend_if_needed,
                                           mock_add_to_group):
        vol_name = VOLUME_WITH_CGROUP["name"] + "-cinder"
        snap_name = "consisgroup-4a2f7e3a-312a-40c5-96a8-536b8a0f" \
                    "e074-cinder.4a2f7e3a-312a-40c5-96a8-536b8a0fe075."\
                    + vol_name
        mock_get_snap_name.return_value = snap_name
        mock_is_replicated_type.return_value = False

        self.driver.create_volume_from_snapshot(VOLUME_WITH_CGROUP,
                                                SNAPSHOT_WITH_CGROUP)

        self.array.copy_volume.assert_called_with(snap_name, vol_name)
        self.assertTrue(mock_get_snap_name.called)
        self.assertTrue(mock_extend_if_needed.called)

        self.driver.create_volume_from_snapshot(VOLUME_WITH_CGROUP,
                                                SNAPSHOT_WITH_CGROUP)
        mock_add_to_group\
            .assert_called_with(VOLUME_WITH_CGROUP,
                                vol_name)

    # Tests cloning a volume that is not replicated type
    @mock.patch(BASE_DRIVER_OBJ + "._add_to_group_if_needed")
    @mock.patch(BASE_DRIVER_OBJ + "._is_volume_replicated_type", autospec=True)
    def test_create_cloned_volume(self, mock_is_replicated_type,
                                  mock_add_to_group):
        vol_name = VOLUME["name"] + "-cinder"
        src_name = SRC_VOL["name"] + "-cinder"
        mock_is_replicated_type.return_value = False
        # Branch where extend unneeded
        self.driver.create_cloned_volume(VOLUME, SRC_VOL)
        self.array.copy_volume.assert_called_with(src_name, vol_name)
        self.assertFalse(self.array.extend_volume.called)
        mock_add_to_group.assert_called_once_with(VOLUME,
                                                  vol_name)
        self.assert_error_propagates(
            [self.array.copy_volume],
            self.driver.create_cloned_volume, VOLUME, SRC_VOL)
        self.assertFalse(self.array.extend_volume.called)

    @mock.patch(BASE_DRIVER_OBJ + "._add_to_group_if_needed")
    @mock.patch(BASE_DRIVER_OBJ + "._is_volume_replicated_type",
                autospec=True)
    def test_create_cloned_volume_and_extend(self, mock_is_replicated_type,
                                             mock_add_to_group):
        vol_name = VOLUME["name"] + "-cinder"
        src_name = SRC_VOL["name"] + "-cinder"
        src = deepcopy(SRC_VOL)
        src["size"] = 1  # resize so smaller than VOLUME
        self.driver.create_cloned_volume(VOLUME, src)
        expected = [mock.call.copy_volume(src_name, vol_name),
                    mock.call.extend_volume(vol_name, 2 * units.Gi)]
        self.array.assert_has_calls(expected)
        mock_add_to_group.assert_called_once_with(VOLUME,
                                                  vol_name)

    # Tests cloning a volume that is part of a consistency group
    @mock.patch(BASE_DRIVER_OBJ + "._add_to_group_if_needed")
    @mock.patch(BASE_DRIVER_OBJ + "._is_volume_replicated_type", autospec=True)
    def test_create_cloned_volume_with_cgroup(self, mock_is_replicated_type,
                                              mock_add_to_group):
        vol_name = VOLUME_WITH_CGROUP["name"] + "-cinder"
        mock_is_replicated_type.return_value = False

        self.driver.create_cloned_volume(VOLUME_WITH_CGROUP, SRC_VOL)

        mock_add_to_group.assert_called_with(VOLUME_WITH_CGROUP,
                                             vol_name)

    def test_delete_volume_already_deleted(self):
        self.array.list_volume_private_connections.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=400,
                text="Volume does not exist"
            )
        self.driver.delete_volume(VOLUME)
        self.assertFalse(self.array.destroy_volume.called)
        self.assertFalse(self.array.eradicate_volume.called)

        # Testing case where array.destroy_volume returns an exception
        # because volume has already been deleted
        self.array.list_volume_private_connections.side_effect = None
        self.array.list_volume_private_connections.return_value = {}
        self.array.destroy_volume.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=http_client.BAD_REQUEST,
                text="Volume does not exist"
            )
        self.driver.delete_volume(VOLUME)
        self.assertTrue(self.array.destroy_volume.called)
        self.assertFalse(self.array.eradicate_volume.called)

    def test_delete_volume(self):
        vol_name = VOLUME["name"] + "-cinder"
        self.array.list_volume_private_connections.return_value = {}
        self.driver.delete_volume(VOLUME)
        expected = [mock.call.destroy_volume(vol_name)]
        self.array.assert_has_calls(expected)
        self.assertFalse(self.array.eradicate_volume.called)
        self.array.destroy_volume.side_effect = (
            self.purestorage_module.PureHTTPError(code=http_client.BAD_REQUEST,
                                                  text="does not exist"))
        self.driver.delete_volume(VOLUME)
        self.array.destroy_volume.side_effect = None
        self.assert_error_propagates([self.array.destroy_volume],
                                     self.driver.delete_volume, VOLUME)

    def test_delete_volume_eradicate_now(self):
        vol_name = VOLUME["name"] + "-cinder"
        self.array.list_volume_private_connections.return_value = {}
        self.mock_config.pure_eradicate_on_delete = True
        self.driver.delete_volume(VOLUME)
        expected = [mock.call.destroy_volume(vol_name),
                    mock.call.eradicate_volume(vol_name)]
        self.array.assert_has_calls(expected)

    def test_delete_connected_volume(self):
        vol_name = VOLUME["name"] + "-cinder"
        host_name_a = "ha"
        host_name_b = "hb"
        self.array.list_volume_private_connections.return_value = [{
            "host": host_name_a,
            "lun": 7,
            "name": vol_name,
            "size": 3221225472,
        }, {
            "host": host_name_b,
            "lun": 2,
            "name": vol_name,
            "size": 3221225472,
        }]

        self.driver.delete_volume(VOLUME)
        expected = [mock.call.list_volume_private_connections(vol_name),
                    mock.call.disconnect_host(host_name_a, vol_name),
                    mock.call.list_host_connections(host_name_a, private=True),
                    mock.call.disconnect_host(host_name_b, vol_name),
                    mock.call.list_host_connections(host_name_b, private=True),
                    mock.call.destroy_volume(vol_name)]
        self.array.assert_has_calls(expected)

    def test_create_snapshot(self):
        vol_name = SRC_VOL["name"] + "-cinder"
        self.driver.create_snapshot(SNAPSHOT)
        self.array.create_snapshot.assert_called_with(
            vol_name,
            suffix=SNAPSHOT["name"]
        )
        self.assert_error_propagates([self.array.create_snapshot],
                                     self.driver.create_snapshot, SNAPSHOT)

    @ddt.data("does not exist", "has been destroyed")
    def test_delete_snapshot(self, error_text):
        snap_name = SNAPSHOT["volume_name"] + "-cinder." + SNAPSHOT["name"]
        self.driver.delete_snapshot(SNAPSHOT)
        expected = [mock.call.destroy_volume(snap_name)]
        self.array.assert_has_calls(expected)
        self.assertFalse(self.array.eradicate_volume.called)
        self.array.destroy_volume.side_effect = (
            self.purestorage_module.PureHTTPError(code=http_client.BAD_REQUEST,
                                                  text=error_text))
        self.driver.delete_snapshot(SNAPSHOT)
        self.array.destroy_volume.side_effect = None
        self.assert_error_propagates([self.array.destroy_volume],
                                     self.driver.delete_snapshot, SNAPSHOT)

    def test_delete_snapshot_eradicate_now(self):
        snap_name = SNAPSHOT["volume_name"] + "-cinder." + SNAPSHOT["name"]
        self.mock_config.pure_eradicate_on_delete = True
        self.driver.delete_snapshot(SNAPSHOT)
        expected = [mock.call.destroy_volume(snap_name),
                    mock.call.eradicate_volume(snap_name)]
        self.array.assert_has_calls(expected)

    @mock.patch(BASE_DRIVER_OBJ + "._get_host", autospec=True)
    def test_terminate_connection(self, mock_host):
        vol_name = VOLUME["name"] + "-cinder"
        mock_host.return_value = {"name": "some-host"}
        # Branch with manually created host
        self.driver.terminate_connection(VOLUME, ISCSI_CONNECTOR)
        self.array.disconnect_host.assert_called_with("some-host", vol_name)
        self.assertTrue(self.array.list_host_connections.called)
        self.assertFalse(self.array.delete_host.called)
        # Branch with host added to host group
        self.array.reset_mock()
        self.array.list_host_connections.return_value = []
        mock_host.return_value = PURE_HOST.copy()
        mock_host.return_value.update(hgroup="some-group")
        self.driver.terminate_connection(VOLUME, ISCSI_CONNECTOR)
        self.array.disconnect_host.assert_called_with(PURE_HOST_NAME, vol_name)
        self.assertTrue(self.array.list_host_connections.called)
        self.assertTrue(self.array.delete_host.called)
        # Branch with host still having connected volumes
        self.array.reset_mock()
        self.array.list_host_connections.return_value = [
            {"lun": 2, "name": PURE_HOST_NAME, "vol": "some-vol"}]
        mock_host.return_value = PURE_HOST
        self.driver.terminate_connection(VOLUME, ISCSI_CONNECTOR)
        self.array.disconnect_host.assert_called_with(PURE_HOST_NAME, vol_name)
        self.array.list_host_connections.assert_called_with(PURE_HOST_NAME,
                                                            private=True)
        self.assertFalse(self.array.delete_host.called)
        # Branch where host gets deleted
        self.array.reset_mock()
        self.array.list_host_connections.return_value = []
        self.driver.terminate_connection(VOLUME, ISCSI_CONNECTOR)
        self.array.disconnect_host.assert_called_with(PURE_HOST_NAME, vol_name)
        self.array.list_host_connections.assert_called_with(PURE_HOST_NAME,
                                                            private=True)
        self.array.delete_host.assert_called_with(PURE_HOST_NAME)
        # Branch where connection is missing and the host is still deleted
        self.array.reset_mock()
        self.array.disconnect_host.side_effect = \
            self.purestorage_module.PureHTTPError(code=http_client.BAD_REQUEST,
                                                  text="is not connected")
        self.driver.terminate_connection(VOLUME, ISCSI_CONNECTOR)
        self.array.disconnect_host.assert_called_with(PURE_HOST_NAME, vol_name)
        self.array.list_host_connections.assert_called_with(PURE_HOST_NAME,
                                                            private=True)
        self.array.delete_host.assert_called_with(PURE_HOST_NAME)
        # Branch where an unexpected exception occurs
        self.array.reset_mock()
        self.array.disconnect_host.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=http_client.INTERNAL_SERVER_ERROR,
                text="Some other error"
            )
        self.assertRaises(self.purestorage_module.PureHTTPError,
                          self.driver.terminate_connection,
                          VOLUME,
                          ISCSI_CONNECTOR)
        self.array.disconnect_host.assert_called_with(PURE_HOST_NAME, vol_name)
        self.assertFalse(self.array.list_host_connections.called)
        self.assertFalse(self.array.delete_host.called)

    def _test_terminate_connection_with_error(self, mock_host, error):
        vol_name = VOLUME["name"] + "-cinder"
        mock_host.return_value = PURE_HOST.copy()
        self.array.reset_mock()
        self.array.list_host_connections.return_value = []
        self.array.delete_host.side_effect = \
            self.purestorage_module.PureHTTPError(code=http_client.BAD_REQUEST,
                                                  text=error)
        self.driver.terminate_connection(VOLUME, ISCSI_CONNECTOR)
        self.array.disconnect_host.assert_called_with(PURE_HOST_NAME, vol_name)
        self.array.list_host_connections.assert_called_with(PURE_HOST_NAME,
                                                            private=True)
        self.array.delete_host.assert_called_once_with(PURE_HOST_NAME)

    @mock.patch(BASE_DRIVER_OBJ + "._get_host", autospec=True)
    def test_terminate_connection_host_deleted(self, mock_host):
        self._test_terminate_connection_with_error(mock_host,
                                                   'Host does not exist.')

    @mock.patch(BASE_DRIVER_OBJ + "._get_host", autospec=True)
    def test_terminate_connection_host_got_new_connections(self, mock_host):
        self._test_terminate_connection_with_error(
            mock_host,
            'Host cannot be deleted due to existing connections.'
        )

    def test_terminate_connection_no_connector_with_host(self):
        # Show the volume having a connection
        self.array.list_volume_private_connections.return_value = \
            [VOLUME_CONNECTIONS[0]]

        self.driver.terminate_connection(VOLUME, None)
        self.array.disconnect_host.assert_called_with(
            VOLUME_CONNECTIONS[0]["host"],
            VOLUME_CONNECTIONS[0]["name"]
        )

    def test_terminate_connection_no_connector_no_host(self):
        vol = fake_volume.fake_volume_obj(None, name=VOLUME["name"])

        # Show the volume having a connection
        self.array.list_volume_private_connections.return_value = []

        # Make sure
        self.driver.terminate_connection(vol, None)
        self.array.disconnect_host.assert_not_called()

    def test_extend_volume(self):
        vol_name = VOLUME["name"] + "-cinder"
        self.driver.extend_volume(VOLUME, 3)
        self.array.extend_volume.assert_called_with(vol_name, 3 * units.Gi)
        self.assert_error_propagates([self.array.extend_volume],
                                     self.driver.extend_volume, VOLUME, 3)

    def test_get_pgroup_name_from_id(self):
        id = "4a2f7e3a-312a-40c5-96a8-536b8a0fe074"
        expected_name = "consisgroup-%s-cinder" % id
        actual_name = self.driver._get_pgroup_name_from_id(id)
        self.assertEqual(expected_name, actual_name)

    def test_get_pgroup_snap_suffix(self):
        cgsnap = {
            'id': "4a2f7e3a-312a-40c5-96a8-536b8a0fe074"
        }
        expected_suffix = "cgsnapshot-%s-cinder" % cgsnap['id']
        actual_suffix = self.driver._get_pgroup_snap_suffix(cgsnap)
        self.assertEqual(expected_suffix, actual_suffix)

    def test_get_pgroup_snap_name(self):
        cg_id = "4a2f7e3a-312a-40c5-96a8-536b8a0fe074"
        cgsnap_id = "4a2f7e3a-312a-40c5-96a8-536b8a0fe075"

        cgsnap = {
            'id': cgsnap_id,
            'group_id': cg_id
        }
        expected_name = "consisgroup-%(cg)s-cinder.cgsnapshot-%(snap)s-cinder"\
                        % {"cg": cg_id, "snap": cgsnap_id}

        actual_name = self.driver._get_pgroup_snap_name(cgsnap)

        self.assertEqual(expected_name, actual_name)

    def test_get_pgroup_snap_name_from_snapshot(self):

        groupsnapshot_id = 'b919b266-23b4-4b83-9a92-e66031b9a921'
        volume_name = 'volume-a3b8b294-8494-4a72-bec7-9aadec561332'
        cg_id = '0cfc0e4e-5029-4839-af20-184fbc42a9ed'
        pgsnap_name_base = (
            'consisgroup-%s-cinder.cgsnapshot-%s-cinder.%s-cinder')
        pgsnap_name = pgsnap_name_base % (cg_id, groupsnapshot_id, volume_name)

        self.driver.db = mock.MagicMock()
        cgsnap = {
            'id': groupsnapshot_id,
            'group_id': cg_id
        }
        self.driver.db.group_snapshot_get.return_value = cgsnap

        mock_snap = mock.MagicMock()
        mock_snap.group_snapshot = cgsnap
        mock_snap.volume_name = volume_name

        actual_name = self.driver._get_pgroup_snap_name_from_snapshot(
            mock_snap
        )
        self.assertEqual(pgsnap_name, actual_name)

    def test_create_consistencygroup(self):
        mock_cgroup = mock.Mock()
        mock_cgroup.id = "4a2f7e3a-312a-40c5-96a8-536b8a0fe074"

        model_update = self.driver.create_consistencygroup(None, mock_cgroup)

        expected_name = self.driver._get_pgroup_name_from_id(mock_cgroup.id)
        self.array.create_pgroup.assert_called_with(expected_name)
        self.assertEqual({'status': 'available'}, model_update)

        self.assert_error_propagates(
            [self.array.create_pgroup],
            self.driver.create_consistencygroup, None, mock_cgroup)

    @mock.patch(BASE_DRIVER_OBJ + ".create_volume_from_snapshot")
    @mock.patch(BASE_DRIVER_OBJ + ".create_consistencygroup")
    def test_create_consistencygroup_from_cgsnapshot(self, mock_create_cg,
                                                     mock_create_vol):
        mock_context = mock.Mock()
        mock_group = mock.Mock()
        mock_cgsnapshot = mock.Mock()
        mock_snapshots = [mock.Mock() for i in range(5)]
        mock_volumes = [mock.Mock() for i in range(5)]
        result = self.driver.create_consistencygroup_from_src(
            mock_context,
            mock_group,
            mock_volumes,
            cgsnapshot=mock_cgsnapshot,
            snapshots=mock_snapshots,
            source_cg=None,
            source_vols=None
        )
        self.assertEqual((None, None), result)
        mock_create_cg.assert_called_with(mock_context, mock_group)
        expected_calls = [mock.call(vol, snap)
                          for vol, snap in zip(mock_volumes, mock_snapshots)]
        mock_create_vol.assert_has_calls(expected_calls,
                                         any_order=True)

        self.assert_error_propagates(
            [mock_create_vol, mock_create_cg],
            self.driver.create_consistencygroup_from_src,
            mock_context,
            mock_group,
            mock_volumes,
            cgsnapshot=mock_cgsnapshot,
            snapshots=mock_snapshots,
            source_cg=None,
            source_vols=None
        )

    @mock.patch(BASE_DRIVER_OBJ + ".create_consistencygroup")
    def test_create_consistencygroup_from_cg(self, mock_create_cg):
        num_volumes = 5
        mock_context = mock.MagicMock()
        mock_group = mock.MagicMock()
        mock_source_cg = mock.MagicMock()
        mock_volumes = [mock.MagicMock() for i in range(num_volumes)]
        mock_source_vols = [mock.MagicMock() for i in range(num_volumes)]
        result = self.driver.create_consistencygroup_from_src(
            mock_context,
            mock_group,
            mock_volumes,
            source_cg=mock_source_cg,
            source_vols=mock_source_vols
        )
        self.assertEqual((None, None), result)
        mock_create_cg.assert_called_with(mock_context, mock_group)
        self.assertTrue(self.array.create_pgroup_snapshot.called)
        self.assertEqual(num_volumes, self.array.copy_volume.call_count)
        self.assertEqual(num_volumes, self.array.set_pgroup.call_count)
        self.assertTrue(self.array.destroy_pgroup.called)

    @mock.patch(BASE_DRIVER_OBJ + ".create_consistencygroup")
    def test_create_consistencygroup_from_cg_with_error(self, mock_create_cg):
        num_volumes = 5
        mock_context = mock.MagicMock()
        mock_group = mock.MagicMock()
        mock_source_cg = mock.MagicMock()
        mock_volumes = [mock.MagicMock() for i in range(num_volumes)]
        mock_source_vols = [mock.MagicMock() for i in range(num_volumes)]

        self.array.copy_volume.side_effect = FakePureStorageHTTPError()

        self.assertRaises(
            FakePureStorageHTTPError,
            self.driver.create_consistencygroup_from_src,
            mock_context,
            mock_group,
            mock_volumes,
            source_cg=mock_source_cg,
            source_vols=mock_source_vols
        )
        mock_create_cg.assert_called_with(mock_context, mock_group)
        self.assertTrue(self.array.create_pgroup_snapshot.called)
        # Make sure that the temp snapshot is cleaned up even when copying
        # the volume fails!
        self.assertTrue(self.array.destroy_pgroup.called)

    @mock.patch(BASE_DRIVER_OBJ + ".delete_volume", autospec=True)
    def test_delete_consistencygroup(self, mock_delete_volume):
        mock_cgroup = mock.MagicMock()
        mock_cgroup.id = "4a2f7e3a-312a-40c5-96a8-536b8a0fe074"
        mock_cgroup['status'] = "deleted"
        mock_context = mock.Mock()
        mock_volume = mock.MagicMock()

        model_update, volumes = self.driver.delete_consistencygroup(
            mock_context, mock_cgroup, [mock_volume])

        expected_name = self.driver._get_pgroup_name_from_id(mock_cgroup.id)
        self.array.destroy_pgroup.assert_called_with(expected_name)
        self.assertFalse(self.array.eradicate_pgroup.called)
        self.assertIsNone(volumes)
        self.assertIsNone(model_update)
        mock_delete_volume.assert_called_with(self.driver, mock_volume)

        self.array.destroy_pgroup.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=http_client.BAD_REQUEST,
                text="Protection group has been destroyed."
            )
        self.driver.delete_consistencygroup(mock_context,
                                            mock_cgroup,
                                            [mock_volume])
        self.array.destroy_pgroup.assert_called_with(expected_name)
        self.assertFalse(self.array.eradicate_pgroup.called)
        mock_delete_volume.assert_called_with(self.driver, mock_volume)

        self.array.destroy_pgroup.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=http_client.BAD_REQUEST,
                text="Protection group does not exist"
            )
        self.driver.delete_consistencygroup(mock_context,
                                            mock_cgroup,
                                            [mock_volume])
        self.array.destroy_pgroup.assert_called_with(expected_name)
        self.assertFalse(self.array.eradicate_pgroup.called)
        mock_delete_volume.assert_called_with(self.driver, mock_volume)

        self.array.destroy_pgroup.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=http_client.BAD_REQUEST,
                text="Some other error"
            )
        self.assertRaises(self.purestorage_module.PureHTTPError,
                          self.driver.delete_consistencygroup,
                          mock_context,
                          mock_volume,
                          [mock_volume])

        self.array.destroy_pgroup.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=http_client.INTERNAL_SERVER_ERROR,
                text="Another different error"
            )
        self.assertRaises(self.purestorage_module.PureHTTPError,
                          self.driver.delete_consistencygroup,
                          mock_context,
                          mock_volume,
                          [mock_volume])

        self.array.destroy_pgroup.side_effect = None
        self.assert_error_propagates(
            [self.array.destroy_pgroup],
            self.driver.delete_consistencygroup,
            mock_context,
            mock_cgroup,
            [mock_volume]
        )

    def _create_mock_cg(self):
        mock_group = mock.MagicMock()
        mock_group.id = "4a2f7e3a-312a-40c5-96a8-536b8a0fe074"
        mock_group.status = "Available"
        mock_group.cg_name = "consisgroup-" + mock_group.id + "-cinder"
        return mock_group

    def test_update_consistencygroup(self):
        mock_group = self._create_mock_cg()
        add_vols = [
            {'name': 'vol1'},
            {'name': 'vol2'},
            {'name': 'vol3'},
        ]
        expected_addvollist = [vol['name'] + '-cinder' for vol in add_vols]
        remove_vols = [
            {'name': 'vol4'},
            {'name': 'vol5'},
        ]
        expected_remvollist = [vol['name'] + '-cinder' for vol in remove_vols]
        self.driver.update_consistencygroup(mock.Mock(), mock_group,
                                            add_vols, remove_vols)
        self.array.set_pgroup.assert_called_with(
            mock_group.cg_name,
            addvollist=expected_addvollist,
            remvollist=expected_remvollist
        )

    def test_update_consistencygroup_no_add_vols(self):
        mock_group = self._create_mock_cg()
        expected_addvollist = []
        remove_vols = [
            {'name': 'vol4'},
            {'name': 'vol5'},
        ]
        expected_remvollist = [vol['name'] + '-cinder' for vol in remove_vols]
        self.driver.update_consistencygroup(mock.Mock(), mock_group,
                                            None, remove_vols)
        self.array.set_pgroup.assert_called_with(
            mock_group.cg_name,
            addvollist=expected_addvollist,
            remvollist=expected_remvollist
        )

    def test_update_consistencygroup_no_remove_vols(self):
        mock_group = self._create_mock_cg()
        add_vols = [
            {'name': 'vol1'},
            {'name': 'vol2'},
            {'name': 'vol3'},
        ]
        expected_addvollist = [vol['name'] + '-cinder' for vol in add_vols]
        expected_remvollist = []
        self.driver.update_consistencygroup(mock.Mock(), mock_group,
                                            add_vols, None)
        self.array.set_pgroup.assert_called_with(
            mock_group.cg_name,
            addvollist=expected_addvollist,
            remvollist=expected_remvollist
        )

    def test_update_consistencygroup_no_vols(self):
        mock_group = self._create_mock_cg()
        self.driver.update_consistencygroup(mock.Mock(), mock_group,
                                            None, None)
        self.array.set_pgroup.assert_called_with(
            mock_group.cg_name,
            addvollist=[],
            remvollist=[]
        )

    def test_create_cgsnapshot(self):
        mock_cgsnap = {
            'id': "4a2f7e3a-312a-40c5-96a8-536b8a0fe074",
            'group_id': "4a2f7e3a-312a-40c5-96a8-536b8a0fe075",
        }
        mock_context = mock.Mock()
        mock_snap = mock.MagicMock()

        model_update, snapshots = self.driver.create_cgsnapshot(mock_context,
                                                                mock_cgsnap,
                                                                [mock_snap])
        cg_id = mock_cgsnap["group_id"]
        expected_pgroup_name = self.driver._get_pgroup_name_from_id(cg_id)
        expected_snap_suffix = self.driver._get_pgroup_snap_suffix(mock_cgsnap)
        self.array.create_pgroup_snapshot\
            .assert_called_with(expected_pgroup_name,
                                suffix=expected_snap_suffix)
        self.assertIsNone(model_update)
        self.assertIsNone(snapshots)

        self.assert_error_propagates(
            [self.array.create_pgroup_snapshot],
            self.driver.create_cgsnapshot, mock_context, mock_cgsnap, [])

    @mock.patch(BASE_DRIVER_OBJ + "._get_pgroup_snap_name",
                spec=pure.PureBaseVolumeDriver._get_pgroup_snap_name)
    def test_delete_cgsnapshot(self, mock_get_snap_name):
        snap_name = "consisgroup-4a2f7e3a-312a-40c5-96a8-536b8a0f" \
                    "e074-cinder.4a2f7e3a-312a-40c5-96a8-536b8a0fe075"
        mock_get_snap_name.return_value = snap_name
        mock_cgsnap = mock.Mock()
        mock_cgsnap.status = 'deleted'
        mock_context = mock.Mock()
        mock_snap = mock.Mock()

        model_update, snapshots = self.driver.delete_cgsnapshot(mock_context,
                                                                mock_cgsnap,
                                                                [mock_snap])

        self.array.destroy_pgroup.assert_called_with(snap_name)
        self.assertFalse(self.array.eradicate_pgroup.called)
        self.assertIsNone(model_update)
        self.assertIsNone(snapshots)

        self.array.destroy_pgroup.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=http_client.BAD_REQUEST,
                text="Protection group snapshot has been destroyed."
            )
        self.driver.delete_cgsnapshot(mock_context, mock_cgsnap, [mock_snap])
        self.array.destroy_pgroup.assert_called_with(snap_name)
        self.assertFalse(self.array.eradicate_pgroup.called)

        self.array.destroy_pgroup.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=http_client.BAD_REQUEST,
                text="Protection group snapshot does not exist"
            )
        self.driver.delete_cgsnapshot(mock_context, mock_cgsnap, [mock_snap])
        self.array.destroy_pgroup.assert_called_with(snap_name)
        self.assertFalse(self.array.eradicate_pgroup.called)

        self.array.destroy_pgroup.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=http_client.BAD_REQUEST,
                text="Some other error"
            )
        self.assertRaises(self.purestorage_module.PureHTTPError,
                          self.driver.delete_cgsnapshot,
                          mock_context,
                          mock_cgsnap,
                          [mock_snap])

        self.array.destroy_pgroup.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=http_client.INTERNAL_SERVER_ERROR,
                text="Another different error"
            )
        self.assertRaises(self.purestorage_module.PureHTTPError,
                          self.driver.delete_cgsnapshot,
                          mock_context,
                          mock_cgsnap,
                          [mock_snap])

        self.array.destroy_pgroup.side_effect = None

        self.assert_error_propagates(
            [self.array.destroy_pgroup],
            self.driver.delete_cgsnapshot,
            mock_context,
            mock_cgsnap,
            [mock_snap]
        )

    @mock.patch(BASE_DRIVER_OBJ + "._get_pgroup_snap_name",
                spec=pure.PureBaseVolumeDriver._get_pgroup_snap_name)
    def test_delete_cgsnapshot_eradicate_now(self, mock_get_snap_name):
        snap_name = "consisgroup-4a2f7e3a-312a-40c5-96a8-536b8a0f" \
                    "e074-cinder.4a2f7e3a-312a-40c5-96a8-536b8a0fe075"
        mock_get_snap_name.return_value = snap_name
        self.mock_config.pure_eradicate_on_delete = True
        model_update, snapshots = self.driver.delete_cgsnapshot(mock.Mock(),
                                                                mock.Mock(),
                                                                [mock.Mock()])

        self.array.destroy_pgroup.assert_called_once_with(snap_name)
        self.array.eradicate_pgroup.assert_called_once_with(snap_name)

    def test_manage_existing(self):
        ref_name = 'vol1'
        volume_ref = {'name': ref_name}
        self.array.list_volume_private_connections.return_value = []
        vol_name = VOLUME['name'] + '-cinder'
        self.driver.manage_existing(VOLUME, volume_ref)
        self.array.list_volume_private_connections.assert_called_with(ref_name)
        self.array.rename_volume.assert_called_with(ref_name, vol_name)

    def test_manage_existing_error_propagates(self):
        self.array.list_volume_private_connections.return_value = []
        self.assert_error_propagates(
            [self.array.list_volume_private_connections,
             self.array.rename_volume],
            self.driver.manage_existing,
            VOLUME, {'name': 'vol1'}
        )

    def test_manage_existing_bad_ref(self):
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing,
                          VOLUME, {'bad_key': 'bad_value'})

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing,
                          VOLUME, {'name': ''})

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing,
                          VOLUME, {'name': None})

        self.array.get_volume.side_effect = \
            self.purestorage_module.PureHTTPError(
                text="Volume does not exist.",
                code=http_client.BAD_REQUEST
            )
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing,
                          VOLUME, {'name': 'non-existing-volume'})

    def test_manage_existing_with_connected_hosts(self):
        ref_name = 'vol1'
        self.array.list_volume_private_connections.return_value = \
            ["host1", "host2"]

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing,
                          VOLUME, {'name': ref_name})

        self.array.list_volume_private_connections.assert_called_with(ref_name)
        self.assertFalse(self.array.rename_volume.called)

    def test_manage_existing_get_size(self):
        ref_name = 'vol1'
        volume_ref = {'name': ref_name}
        expected_size = 5
        self.array.get_volume.return_value = {"size": 5368709120}

        size = self.driver.manage_existing_get_size(VOLUME, volume_ref)

        self.assertEqual(expected_size, size)
        self.array.get_volume.assert_called_with(ref_name, snap=False)

    def test_manage_existing_get_size_error_propagates(self):
        self.array.get_volume.return_value = mock.MagicMock()
        self.assert_error_propagates([self.array.get_volume],
                                     self.driver.manage_existing_get_size,
                                     VOLUME, {'name': 'vol1'})

    def test_manage_existing_get_size_bad_ref(self):
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size,
                          VOLUME, {'bad_key': 'bad_value'})

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size,
                          VOLUME, {'name': ''})

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size,
                          VOLUME, {'name': None})

    def test_unmanage(self):
        vol_name = VOLUME['name'] + "-cinder"
        unmanaged_vol_name = vol_name + "-unmanaged"

        self.driver.unmanage(VOLUME)

        self.array.rename_volume.assert_called_with(vol_name,
                                                    unmanaged_vol_name)

    def test_unmanage_error_propagates(self):
        self.assert_error_propagates([self.array.rename_volume],
                                     self.driver.unmanage,
                                     VOLUME)

    def test_unmanage_with_deleted_volume(self):
        vol_name = VOLUME['name'] + "-cinder"
        unmanaged_vol_name = vol_name + "-unmanaged"
        self.array.rename_volume.side_effect = \
            self.purestorage_module.PureHTTPError(
                text="Volume does not exist.",
                code=http_client.BAD_REQUEST
            )

        self.driver.unmanage(VOLUME)

        self.array.rename_volume.assert_called_with(vol_name,
                                                    unmanaged_vol_name)

    def test_manage_existing_snapshot(self):
        ref_name = PURE_SNAPSHOT['name']
        snap_ref = {'name': ref_name}
        self.array.get_volume.return_value = [PURE_SNAPSHOT]
        self.driver.manage_existing_snapshot(SNAPSHOT, snap_ref)
        self.array.rename_volume.assert_called_once_with(ref_name,
                                                         SNAPSHOT_PURITY_NAME)
        self.array.get_volume.assert_called_with(PURE_SNAPSHOT['source'],
                                                 snap=True)

    def test_manage_existing_snapshot_multiple_snaps_on_volume(self):
        ref_name = PURE_SNAPSHOT['name']
        snap_ref = {'name': ref_name}
        pure_snaps = [PURE_SNAPSHOT]
        for i in range(5):
            snap = PURE_SNAPSHOT.copy()
            snap['name'] += str(i)
            pure_snaps.append(snap)
        self.array.get_volume.return_value = pure_snaps
        self.driver.manage_existing_snapshot(SNAPSHOT, snap_ref)
        self.array.rename_volume.assert_called_once_with(ref_name,
                                                         SNAPSHOT_PURITY_NAME)

    def test_manage_existing_snapshot_error_propagates(self):
        self.array.get_volume.return_value = [PURE_SNAPSHOT]
        self.assert_error_propagates(
            [self.array.rename_volume],
            self.driver.manage_existing_snapshot,
            SNAPSHOT, {'name': PURE_SNAPSHOT['name']}
        )

    def test_manage_existing_snapshot_bad_ref(self):
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot,
                          SNAPSHOT, {'bad_key': 'bad_value'})

    def test_manage_existing_snapshot_empty_ref(self):
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot,
                          SNAPSHOT, {'name': ''})

    def test_manage_existing_snapshot_none_ref(self):
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot,
                          SNAPSHOT, {'name': None})

    def test_manage_existing_snapshot_volume_ref_not_exist(self):
        self.array.get_volume.side_effect = \
            self.purestorage_module.PureHTTPError(
                text="Volume does not exist.",
                code=http_client.BAD_REQUEST
            )
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot,
                          SNAPSHOT, {'name': 'non-existing-volume.snap1'})

    def test_manage_existing_snapshot_ref_not_exist(self):
        ref_name = PURE_SNAPSHOT['name'] + '-fake'
        snap_ref = {'name': ref_name}
        self.array.get_volume.return_value = [PURE_SNAPSHOT]
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot,
                          SNAPSHOT, snap_ref)

    def test_manage_existing_snapshot_bad_api_version(self):
        self.array.get_rest_version.return_value = '1.3'
        self.assertRaises(exception.PureDriverException,
                          self.driver.manage_existing_snapshot,
                          SNAPSHOT, {'name': PURE_SNAPSHOT['name']})

    def test_manage_existing_snapshot_get_size(self):
        ref_name = PURE_SNAPSHOT['name']
        snap_ref = {'name': ref_name}
        self.array.get_volume.return_value = [PURE_SNAPSHOT]

        size = self.driver.manage_existing_snapshot_get_size(SNAPSHOT,
                                                             snap_ref)
        expected_size = 3.0
        self.assertEqual(expected_size, size)
        self.array.get_volume.assert_called_with(PURE_SNAPSHOT['source'],
                                                 snap=True)

    def test_manage_existing_snapshot_get_size_error_propagates(self):
        self.array.get_volume.return_value = [PURE_SNAPSHOT]
        self.assert_error_propagates(
            [self.array.get_volume],
            self.driver.manage_existing_snapshot_get_size,
            SNAPSHOT, {'name': PURE_SNAPSHOT['name']}
        )

    def test_manage_existing_snapshot_get_size_bad_ref(self):
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot_get_size,
                          SNAPSHOT, {'bad_key': 'bad_value'})

    def test_manage_existing_snapshot_get_size_empty_ref(self):
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot_get_size,
                          SNAPSHOT, {'name': ''})

    def test_manage_existing_snapshot_get_size_none_ref(self):
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot_get_size,
                          SNAPSHOT, {'name': None})

    def test_manage_existing_snapshot_get_size_volume_ref_not_exist(self):
        self.array.get_volume.side_effect = \
            self.purestorage_module.PureHTTPError(
                text="Volume does not exist.",
                code=http_client.BAD_REQUEST
            )
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot_get_size,
                          SNAPSHOT, {'name': 'non-existing-volume.snap1'})

    def test_manage_existing_snapshot_get_size_bad_api_version(self):
        self.array.get_rest_version.return_value = '1.3'
        self.assertRaises(exception.PureDriverException,
                          self.driver.manage_existing_snapshot_get_size,
                          SNAPSHOT, {'name': PURE_SNAPSHOT['name']})

    def test_unmanage_snapshot(self):
        unmanaged_snap_name = SNAPSHOT_PURITY_NAME + "-unmanaged"
        self.driver.unmanage_snapshot(SNAPSHOT)
        self.array.rename_volume.assert_called_with(SNAPSHOT_PURITY_NAME,
                                                    unmanaged_snap_name)

    def test_unmanage_snapshot_error_propagates(self):
        self.assert_error_propagates([self.array.rename_volume],
                                     self.driver.unmanage_snapshot,
                                     SNAPSHOT)

    def test_unmanage_snapshot_with_deleted_snapshot(self):
        unmanaged_snap_name = SNAPSHOT_PURITY_NAME + "-unmanaged"
        self.array.rename_volume.side_effect = \
            self.purestorage_module.PureHTTPError(
                text="Snapshot does not exist.",
                code=http_client.BAD_REQUEST
            )

        self.driver.unmanage_snapshot(SNAPSHOT)

        self.array.rename_volume.assert_called_with(SNAPSHOT_PURITY_NAME,
                                                    unmanaged_snap_name)

    def test_unmanage_snapshot_bad_api_version(self):
        self.array.get_rest_version.return_value = '1.3'
        self.assertRaises(exception.PureDriverException,
                          self.driver.unmanage_snapshot,
                          SNAPSHOT)

    def _test_retype_repl(self, mock_is_repl, is_vol_repl,
                          repl_cabability, volume_id=None):
        mock_is_repl.return_value = is_vol_repl
        context = mock.MagicMock()
        volume = fake_volume.fake_volume_obj(context)
        if volume_id:
            volume.id = volume_id
        new_type = {
            'extra_specs': {
                pure.EXTRA_SPECS_REPL_ENABLED:
                '<is> ' + str(repl_cabability)
            }
        }

        actual = self.driver.retype(context, volume, new_type, None, None)
        expected = (True, None)
        self.assertEqual(expected, actual)
        return context, volume

    def _test_get_manageable_things(self,
                                    pure_objs=MANAGEABLE_PURE_VOLS,
                                    expected_refs=MANAGEABLE_PURE_VOL_REFS,
                                    pure_hosts=list(),
                                    cinder_objs=list(),
                                    is_snapshot=False):
        self.array.list_volumes.return_value = pure_objs
        self.array.list_hosts.return_value = pure_hosts
        marker = mock.Mock()
        limit = mock.Mock()
        offset = mock.Mock()
        sort_keys = mock.Mock()
        sort_dirs = mock.Mock()

        with mock.patch('cinder.volume.utils.paginate_entries_list') as mpage:
            if is_snapshot:
                test_func = self.driver.get_manageable_snapshots
            else:
                test_func = self.driver.get_manageable_volumes
            test_func(cinder_objs, marker, limit, offset, sort_keys, sort_dirs)
            mpage.assert_called_once_with(
                expected_refs,
                marker,
                limit,
                offset,
                sort_keys,
                sort_dirs
            )

    def test_get_manageable_volumes(self,):
        """Default success case.

        Given a list of pure volumes from the REST API, give back a list
        of volume references.
        """
        self._test_get_manageable_things(pure_hosts=[PURE_HOST])

    def test_get_manageable_volumes_connected_vol(self):
        """Make sure volumes connected to hosts are flagged as unsafe."""
        connected_host = deepcopy(PURE_HOST)
        connected_host['name'] = 'host2'
        connected_host['vol'] = MANAGEABLE_PURE_VOLS[0]['name']
        pure_hosts = [PURE_HOST, connected_host]

        expected_refs = deepcopy(MANAGEABLE_PURE_VOL_REFS)
        expected_refs[0]['safe_to_manage'] = False
        expected_refs[0]['reason_not_safe'] = 'Volume connected to host host2.'

        self._test_get_manageable_things(expected_refs=expected_refs,
                                         pure_hosts=pure_hosts)

    def test_get_manageable_volumes_already_managed(self):
        """Make sure volumes already owned by cinder are flagged as unsafe."""
        cinder_vol = fake_volume.fake_volume_obj(mock.MagicMock())
        cinder_vol.id = VOLUME_ID
        cinders_vols = [cinder_vol]

        # Have one of our vol names match up with the existing cinder volume
        purity_vols = deepcopy(MANAGEABLE_PURE_VOLS)
        purity_vols[0]['name'] = 'volume-' + VOLUME_ID + '-cinder'

        expected_refs = deepcopy(MANAGEABLE_PURE_VOL_REFS)
        expected_refs[0]['reference'] = {'name': purity_vols[0]['name']}
        expected_refs[0]['safe_to_manage'] = False
        expected_refs[0]['reason_not_safe'] = 'Volume already managed.'
        expected_refs[0]['cinder_id'] = VOLUME_ID

        self._test_get_manageable_things(pure_objs=purity_vols,
                                         expected_refs=expected_refs,
                                         pure_hosts=[PURE_HOST],
                                         cinder_objs=cinders_vols)

    def test_get_manageable_volumes_no_pure_volumes(self):
        """Expect no refs to be found if no volumes are on Purity."""
        self._test_get_manageable_things(pure_objs=[],
                                         expected_refs=[],
                                         pure_hosts=[PURE_HOST])

    def test_get_manageable_volumes_no_hosts(self):
        """Success case with no hosts on Purity."""
        self._test_get_manageable_things(pure_hosts=[])

    def test_get_manageable_snapshots(self):
        """Default success case.

        Given a list of pure snapshots from the REST API, give back a list
        of snapshot references.
        """
        self._test_get_manageable_things(
            pure_objs=MANAGEABLE_PURE_SNAPS,
            expected_refs=MANAGEABLE_PURE_SNAP_REFS,
            pure_hosts=[PURE_HOST],
            is_snapshot=True
        )

    def test_get_manageable_snapshots_already_managed(self):
        """Make sure snaps already owned by cinder are flagged as unsafe."""
        cinder_vol = fake_volume.fake_volume_obj(mock.MagicMock())
        cinder_vol.id = VOLUME_ID
        cinder_snap = fake_snapshot.fake_snapshot_obj(mock.MagicMock())
        cinder_snap.id = SNAPSHOT_ID
        cinder_snap.volume = cinder_vol
        cinder_snaps = [cinder_snap]

        purity_snaps = deepcopy(MANAGEABLE_PURE_SNAPS)
        purity_snaps[0]['name'] = 'volume-%s-cinder.snapshot-%s' % (
            VOLUME_ID, SNAPSHOT_ID
        )

        expected_refs = deepcopy(MANAGEABLE_PURE_SNAP_REFS)
        expected_refs[0]['reference'] = {'name': purity_snaps[0]['name']}
        expected_refs[0]['safe_to_manage'] = False
        expected_refs[0]['reason_not_safe'] = 'Snapshot already managed.'
        expected_refs[0]['cinder_id'] = SNAPSHOT_ID

        self._test_get_manageable_things(
            pure_objs=purity_snaps,
            expected_refs=expected_refs,
            cinder_objs=cinder_snaps,
            pure_hosts=[PURE_HOST],
            is_snapshot=True
        )

    def test_get_manageable_snapshots_no_pure_snapshots(self):
        """Expect no refs to be found if no snapshots are on Purity."""
        self._test_get_manageable_things(pure_objs=[],
                                         expected_refs=[],
                                         pure_hosts=[PURE_HOST],
                                         is_snapshot=True)

    @mock.patch(BASE_DRIVER_OBJ + '._is_volume_replicated_type', autospec=True)
    def test_retype_repl_to_repl(self, mock_is_replicated_type):
        self._test_retype_repl(mock_is_replicated_type, True, True)

    @mock.patch(BASE_DRIVER_OBJ + '._is_volume_replicated_type', autospec=True)
    def test_retype_non_repl_to_non_repl(self, mock_is_replicated_type):
        self._test_retype_repl(mock_is_replicated_type, False, False)

    @mock.patch(BASE_DRIVER_OBJ + '._is_volume_replicated_type', autospec=True)
    def test_retype_non_repl_to_repl(self, mock_is_replicated_type):

        context, volume = self._test_retype_repl(mock_is_replicated_type,
                                                 False,
                                                 True,
                                                 volume_id=VOLUME_ID)
        self.array.set_pgroup.assert_called_once_with(
            pure.REPLICATION_CG_NAME,
            addvollist=[VOLUME_PURITY_NAME]
        )

    @mock.patch(BASE_DRIVER_OBJ + '._is_volume_replicated_type', autospec=True)
    def test_retype_repl_to_non_repl(self, mock_is_replicated_type,):
        context, volume = self._test_retype_repl(mock_is_replicated_type,
                                                 True,
                                                 False,
                                                 volume_id=VOLUME_ID)
        self.array.set_pgroup.assert_called_once_with(
            pure.REPLICATION_CG_NAME,
            remvollist=[VOLUME_PURITY_NAME]
        )

    @mock.patch('cinder.volume.volume_types.get_volume_type')
    def test_is_vol_replicated_no_extra_specs(self, mock_get_vol_type):
        mock_get_vol_type.return_value = NON_REPLICATED_VOL_TYPE
        volume = fake_volume.fake_volume_obj(mock.MagicMock())
        actual = self.driver._is_volume_replicated_type(volume)
        self.assertFalse(actual)

    @mock.patch('cinder.volume.volume_types.get_volume_type')
    def test_is_vol_replicated_has_repl_extra_specs(self, mock_get_vol_type):
        mock_get_vol_type.return_value = REPLICATED_VOL_TYPE
        volume = fake_volume.fake_volume_obj(mock.MagicMock())
        volume.volume_type_id = REPLICATED_VOL_TYPE['id']
        actual = self.driver._is_volume_replicated_type(volume)
        self.assertTrue(actual)

    @mock.patch('cinder.volume.volume_types.get_volume_type')
    def test_is_vol_replicated_none_type(self, mock_get_vol_type):
        mock_get_vol_type.side_effect = exception.InvalidVolumeType(reason='')
        volume = fake_volume.fake_volume_obj(mock.MagicMock())
        volume.volume_type = None
        volume.volume_type_id = None
        actual = self.driver._is_volume_replicated_type(volume)
        self.assertFalse(actual)

    @mock.patch('cinder.volume.volume_types.get_volume_type')
    def test_is_vol_replicated_has_other_extra_specs(self, mock_get_vol_type):
        vtype_test = deepcopy(NON_REPLICATED_VOL_TYPE)
        vtype_test["extra_specs"] = {"some_key": "some_value"}
        mock_get_vol_type.return_value = vtype_test
        volume = fake_volume.fake_volume_obj(mock.MagicMock())
        actual = self.driver._is_volume_replicated_type(volume)
        self.assertFalse(actual)

    def test_does_pgroup_exist_not_exists(self):
        self.array.get_pgroup.side_effect = (
            self.purestorage_module.PureHTTPError(code=http_client.BAD_REQUEST,
                                                  text="does not exist"))
        exists = self.driver._does_pgroup_exist(self.array, "some_pgroup")
        self.assertFalse(exists)

    def test_does_pgroup_exist_exists(self):
        self.array.get_pgroup.side_effect = None
        self.array.get_pgroup.return_value = PGROUP_ON_TARGET_NOT_ALLOWED
        exists = self.driver._does_pgroup_exist(self.array, "some_pgroup")
        self.assertTrue(exists)

    def test_does_pgroup_exist_error_propagates(self):
        self.assert_error_propagates([self.array.get_pgroup],
                                     self.driver._does_pgroup_exist,
                                     self.array,
                                     "some_pgroup")

    @mock.patch(BASE_DRIVER_OBJ + "._does_pgroup_exist")
    def test_wait_until_target_group_setting_propagates_ready(self,
                                                              mock_exists):
        mock_exists.return_value = True
        self.driver._wait_until_target_group_setting_propagates(
            self.array,
            "some_pgroup"
        )

    @mock.patch(BASE_DRIVER_OBJ + "._does_pgroup_exist")
    def test_wait_until_target_group_setting_propagates_not_ready(self,
                                                                  mock_exists):
        mock_exists.return_value = False
        self.assertRaises(
            exception.PureDriverException,
            self.driver._wait_until_target_group_setting_propagates,
            self.array,
            "some_pgroup"
        )

    def test_wait_until_source_array_allowed_ready(self):
        self.array.get_pgroup.return_value = PGROUP_ON_TARGET_ALLOWED
        self.driver._wait_until_source_array_allowed(
            self.array,
            "some_pgroup",)

    def test_wait_until_source_array_allowed_not_ready(self):
        self.array.get_pgroup.return_value = PGROUP_ON_TARGET_NOT_ALLOWED
        self.assertRaises(
            exception.PureDriverException,
            self.driver._wait_until_source_array_allowed,
            self.array,
            "some_pgroup",
        )

    @mock.patch('cinder.volume.volume_types.get_volume_type')
    def test_create_volume_replicated(self, mock_get_volume_type):
        mock_get_volume_type.return_value = REPLICATED_VOL_TYPE
        self._setup_mocks_for_replication()
        self.driver._array = self.array
        self.driver._array.array_name = GET_ARRAY_PRIMARY["array_name"]
        self.driver._array.array_id = GET_ARRAY_PRIMARY["id"]
        self.driver._replication_target_arrays = [mock.Mock()]
        self.driver._replication_target_arrays[0].array_name = (
            GET_ARRAY_SECONDARY["array_name"])
        self.driver.create_volume(VOLUME)
        self.array.create_volume.assert_called_with(
            VOLUME["name"] + "-cinder", 2 * units.Gi)
        self.array.set_pgroup.assert_called_with(
            REPLICATION_PROTECTION_GROUP,
            addvollist=[VOLUME["name"] + "-cinder"])

    def test_find_failover_target_no_repl_targets(self):
        self.driver._replication_target_arrays = []
        self.assertRaises(exception.PureDriverException,
                          self.driver._find_failover_target,
                          None)

    @mock.patch(BASE_DRIVER_OBJ + '._get_latest_replicated_pg_snap')
    def test_find_failover_target_secondary_specified(self, mock_get_snap):
        mock_backend_1 = mock.Mock()
        mock_backend_2 = mock.Mock()
        secondary_id = 'foo'
        mock_backend_2._backend_id = secondary_id
        self.driver._replication_target_arrays = [mock_backend_1,
                                                  mock_backend_2]
        mock_get_snap.return_value = REPLICATED_PGSNAPS[0]

        array, pg_snap = self.driver._find_failover_target(secondary_id)
        self.assertEqual(mock_backend_2, array)
        self.assertEqual(REPLICATED_PGSNAPS[0], pg_snap)

    def test_find_failover_target_secondary_specified_not_found(self):
        mock_backend = mock.Mock()
        mock_backend._backend_id = 'not_foo'
        self.driver._replication_target_arrays = [mock_backend]
        self.assertRaises(exception.InvalidReplicationTarget,
                          self.driver._find_failover_target,
                          'foo')

    @mock.patch(BASE_DRIVER_OBJ + '._get_latest_replicated_pg_snap')
    def test_find_failover_target_secondary_specified_no_pgsnap(self,
                                                                mock_get_snap):
        mock_backend = mock.Mock()
        secondary_id = 'foo'
        mock_backend._backend_id = secondary_id
        self.driver._replication_target_arrays = [mock_backend]
        mock_get_snap.return_value = None

        self.assertRaises(exception.PureDriverException,
                          self.driver._find_failover_target,
                          secondary_id)

    @mock.patch(BASE_DRIVER_OBJ + '._get_latest_replicated_pg_snap')
    def test_find_failover_target_no_secondary_specified(self,
                                                         mock_get_snap):
        mock_backend_1 = mock.Mock()
        mock_backend_2 = mock.Mock()
        self.driver._replication_target_arrays = [mock_backend_1,
                                                  mock_backend_2]
        mock_get_snap.return_value = REPLICATED_PGSNAPS[0]

        array, pg_snap = self.driver._find_failover_target(None)
        self.assertEqual(mock_backend_1, array)
        self.assertEqual(REPLICATED_PGSNAPS[0], pg_snap)

    @mock.patch(BASE_DRIVER_OBJ + '._get_latest_replicated_pg_snap')
    def test_find_failover_target_no_secondary_specified_missing_pgsnap(
            self, mock_get_snap):
        mock_backend_1 = mock.Mock()
        mock_backend_2 = mock.Mock()
        self.driver._replication_target_arrays = [mock_backend_1,
                                                  mock_backend_2]
        mock_get_snap.side_effect = [None, REPLICATED_PGSNAPS[0]]

        array, pg_snap = self.driver._find_failover_target(None)
        self.assertEqual(mock_backend_2, array)
        self.assertEqual(REPLICATED_PGSNAPS[0], pg_snap)

    @mock.patch(BASE_DRIVER_OBJ + '._get_latest_replicated_pg_snap')
    def test_find_failover_target_no_secondary_specified_no_pgsnap(
            self, mock_get_snap):
        mock_backend = mock.Mock()
        self.driver._replication_target_arrays = [mock_backend]
        mock_get_snap.return_value = None

        self.assertRaises(exception.PureDriverException,
                          self.driver._find_failover_target,
                          None)

    @mock.patch(BASE_DRIVER_OBJ + '._get_latest_replicated_pg_snap')
    def test_find_failover_target_error_propagates_secondary_specified(
            self, mock_get_snap):
        mock_backend = mock.Mock()
        mock_backend._backend_id = 'foo'
        self.driver._replication_target_arrays = [mock_backend]
        self.assert_error_propagates(
            [mock_get_snap],
            self.driver._find_failover_target,
            'foo'
        )

    @mock.patch(BASE_DRIVER_OBJ + '._get_latest_replicated_pg_snap')
    def test_find_failover_target_error_propagates_no_secondary(
            self, mock_get_snap):
        self.driver._replication_target_arrays = [mock.Mock()]
        self.assert_error_propagates(
            [mock_get_snap],
            self.driver._find_failover_target,
            None
        )

    @mock.patch('cinder.volume.volume_types.get_volume_type')
    def test_enable_replication_if_needed_success(
            self, mock_get_volume_type):
        mock_get_volume_type.return_value = REPLICATED_VOL_TYPE
        self.driver._enable_replication_if_needed(self.array, VOLUME)

        self.array.set_pgroup.assert_called_with(
            self.driver._replication_pg_name,
            addvollist=[VOLUME_PURITY_NAME]
        )

    @mock.patch('cinder.volume.volume_types.get_volume_type')
    def test_enable_replication_if_needed_not_repl_type(
            self, mock_get_volume_type):
        mock_get_volume_type.return_value = NON_REPLICATED_VOL_TYPE
        self.driver._enable_replication_if_needed(self.array, VOLUME)
        self.assertFalse(self.array.set_pgroup.called)

    @mock.patch('cinder.volume.volume_types.get_volume_type')
    def test_enable_replication_if_needed_already_repl(
            self, mock_get_volume_type):
        mock_get_volume_type.return_value = REPLICATED_VOL_TYPE
        self.array.set_pgroup.side_effect = FakePureStorageHTTPError(
            code=http_client.BAD_REQUEST, text='already belongs to')
        self.driver._enable_replication_if_needed(self.array, VOLUME)
        self.array.set_pgroup.assert_called_with(
            self.driver._replication_pg_name,
            addvollist=[VOLUME_PURITY_NAME]
        )

    @mock.patch('cinder.volume.volume_types.get_volume_type')
    def test_enable_replication_if_needed_error_propagates(
            self, mock_get_volume_type):
        mock_get_volume_type.return_value = REPLICATED_VOL_TYPE
        self.driver._enable_replication_if_needed(self.array, VOLUME)
        self.assert_error_propagates(
            [self.array.set_pgroup],
            self.driver._enable_replication,
            self.array, VOLUME
        )

    @mock.patch(BASE_DRIVER_OBJ + '._get_flasharray')
    @mock.patch(BASE_DRIVER_OBJ + '._find_failover_target')
    def test_failover(self, mock_find_failover_target, mock_get_array):
        secondary_device_id = 'foo'
        self.array2._backend_id = secondary_device_id
        self.driver._replication_target_arrays = [self.array2]

        array2_v1_3 = mock.Mock()
        array2_v1_3._backend_id = secondary_device_id
        array2_v1_3.array_name = GET_ARRAY_SECONDARY['array_name']
        array2_v1_3.array_id = GET_ARRAY_SECONDARY['id']
        array2_v1_3.version = '1.3'
        mock_get_array.return_value = array2_v1_3

        target_array = self.array2
        target_array.copy_volume = mock.Mock()

        mock_find_failover_target.return_value = (
            target_array,
            REPLICATED_PGSNAPS[1]
        )

        array2_v1_3.get_volume.return_value = REPLICATED_VOLUME_SNAPS

        context = mock.MagicMock()
        new_active_id, volume_updates, __ = self.driver.failover_host(
            context,
            REPLICATED_VOLUME_OBJS,
            None,
            []
        )

        self.assertEqual(secondary_device_id, new_active_id)
        self.assertEqual([], volume_updates)

        calls = []
        for snap in REPLICATED_VOLUME_SNAPS:
            vol_name = snap['name'].split('.')[-1]
            calls.append(mock.call(
                snap['name'],
                vol_name,
                overwrite=True
            ))
        target_array.copy_volume.assert_has_calls(calls, any_order=True)

    @mock.patch(BASE_DRIVER_OBJ + '._get_flasharray')
    @mock.patch(BASE_DRIVER_OBJ + '._find_failover_target')
    def test_failover_error_propagates(self, mock_find_failover_target,
                                       mock_get_array):
        mock_find_failover_target.return_value = (
            self.array2,
            REPLICATED_PGSNAPS[1]
        )

        array2_v1_3 = mock.Mock()
        array2_v1_3.array_name = GET_ARRAY_SECONDARY['array_name']
        array2_v1_3.array_id = GET_ARRAY_SECONDARY['id']
        array2_v1_3.version = '1.3'
        mock_get_array.return_value = array2_v1_3

        array2_v1_3.get_volume.return_value = REPLICATED_VOLUME_SNAPS
        self.assert_error_propagates(
            [mock_find_failover_target,
             mock_get_array,
             array2_v1_3.get_volume,
             self.array2.copy_volume],
            self.driver.failover_host,
            mock.Mock(), REPLICATED_VOLUME_OBJS, None
        )

    def test_disable_replication_success(self):
        self.driver._disable_replication(VOLUME)
        self.array.set_pgroup.assert_called_with(
            self.driver._replication_pg_name,
            remvollist=[VOLUME_PURITY_NAME]
        )

    def test_disable_replication_error_propagates(self):
        self.assert_error_propagates(
            [self.array.set_pgroup],
            self.driver._disable_replication,
            VOLUME
        )

    def test_disable_replication_already_disabled(self):
        self.array.set_pgroup.side_effect = FakePureStorageHTTPError(
            code=http_client.BAD_REQUEST, text='could not be found')
        self.driver._disable_replication(VOLUME)
        self.array.set_pgroup.assert_called_with(
            self.driver._replication_pg_name,
            remvollist=[VOLUME_PURITY_NAME]
        )

    def test_get_flasharray_verify_https(self):
        san_ip = '1.2.3.4'
        api_token = 'abcdef'
        cert_path = '/my/ssl/certs'
        self.purestorage_module.FlashArray.return_value = mock.MagicMock()

        self.driver._get_flasharray(san_ip,
                                    api_token,
                                    verify_https=True,
                                    ssl_cert_path=cert_path)
        self.purestorage_module.FlashArray.assert_called_with(
            san_ip,
            api_token=api_token,
            rest_version=None,
            verify_https=True,
            ssl_cert=cert_path,
            user_agent=self.driver._user_agent,
        )


class PureISCSIDriverTestCase(PureDriverTestCase):

    def setUp(self):
        super(PureISCSIDriverTestCase, self).setUp()
        self.mock_config.use_chap_auth = False
        self.driver = pure.PureISCSIDriver(configuration=self.mock_config)
        self.driver._array = self.array
        self.mock_utils = mock.Mock()
        self.driver.driver_utils = self.mock_utils

    def test_get_host(self):
        good_host = PURE_HOST.copy()
        good_host.update(iqn=["another-wrong-iqn", INITIATOR_IQN])
        bad_host = {"name": "bad-host", "iqn": ["wrong-iqn"]}
        self.array.list_hosts.return_value = [bad_host]
        real_result = self.driver._get_host(self.array, ISCSI_CONNECTOR)
        self.assertIsNone(real_result)
        self.array.list_hosts.return_value.append(good_host)
        real_result = self.driver._get_host(self.array, ISCSI_CONNECTOR)
        self.assertEqual(good_host, real_result)
        self.assert_error_propagates([self.array.list_hosts],
                                     self.driver._get_host,
                                     self.array,
                                     ISCSI_CONNECTOR)

    @mock.patch(ISCSI_DRIVER_OBJ + "._connect")
    @mock.patch(ISCSI_DRIVER_OBJ + "._get_target_iscsi_ports")
    def test_initialize_connection(self, mock_get_iscsi_ports,
                                   mock_connection):
        mock_get_iscsi_ports.return_value = ISCSI_PORTS
        lun = 1
        connection = {
            "vol": VOLUME["name"] + "-cinder",
            "lun": lun,
        }
        mock_connection.return_value = connection
        result = deepcopy(ISCSI_CONNECTION_INFO)

        real_result = self.driver.initialize_connection(VOLUME,
                                                        ISCSI_CONNECTOR)
        self.assertDictEqual(result, real_result)
        mock_get_iscsi_ports.assert_called_with()
        mock_connection.assert_called_with(VOLUME, ISCSI_CONNECTOR)
        self.assert_error_propagates([mock_get_iscsi_ports, mock_connection],
                                     self.driver.initialize_connection,
                                     VOLUME, ISCSI_CONNECTOR)

    @mock.patch(ISCSI_DRIVER_OBJ + "._connect")
    @mock.patch(ISCSI_DRIVER_OBJ + "._get_target_iscsi_ports")
    def test_initialize_connection_with_auth(self, mock_get_iscsi_ports,
                                             mock_connection):
        auth_type = "CHAP"
        chap_username = ISCSI_CONNECTOR["host"]
        chap_password = "password"
        mock_get_iscsi_ports.return_value = ISCSI_PORTS
        mock_connection.return_value = {
            "vol": VOLUME["name"] + "-cinder",
            "lun": 1,
            "auth_username": chap_username,
            "auth_password": chap_password,
        }
        result = deepcopy(ISCSI_CONNECTION_INFO)
        result["data"]["auth_method"] = auth_type
        result["data"]["auth_username"] = chap_username
        result["data"]["auth_password"] = chap_password

        self.mock_config.use_chap_auth = True

        # Branch where no credentials were generated
        real_result = self.driver.initialize_connection(VOLUME,
                                                        ISCSI_CONNECTOR)
        mock_connection.assert_called_with(VOLUME, ISCSI_CONNECTOR)
        self.assertDictEqual(result, real_result)

        self.assert_error_propagates([mock_get_iscsi_ports, mock_connection],
                                     self.driver.initialize_connection,
                                     VOLUME, ISCSI_CONNECTOR)

    @mock.patch(ISCSI_DRIVER_OBJ + "._connect")
    @mock.patch(ISCSI_DRIVER_OBJ + "._get_target_iscsi_ports")
    def test_initialize_connection_multipath(self,
                                             mock_get_iscsi_ports,
                                             mock_connection):
        mock_get_iscsi_ports.return_value = ISCSI_PORTS
        lun = 1
        connection = {
            "vol": VOLUME["name"] + "-cinder",
            "lun": lun,
        }
        mock_connection.return_value = connection
        multipath_connector = deepcopy(ISCSI_CONNECTOR)
        multipath_connector["multipath"] = True
        result = deepcopy(ISCSI_CONNECTION_INFO)

        real_result = self.driver.initialize_connection(VOLUME,
                                                        multipath_connector)
        self.assertDictEqual(result, real_result)
        mock_get_iscsi_ports.assert_called_with()
        mock_connection.assert_called_with(VOLUME, multipath_connector)

        multipath_connector["multipath"] = False
        self.driver.initialize_connection(VOLUME, multipath_connector)

    def test_get_target_iscsi_ports(self):
        self.array.list_ports.return_value = ISCSI_PORTS
        ret = self.driver._get_target_iscsi_ports()
        self.assertEqual(ISCSI_PORTS, ret)

    def test_get_target_iscsi_ports_with_iscsi_and_fc(self):
        self.array.list_ports.return_value = PORTS_WITH
        ret = self.driver._get_target_iscsi_ports()
        self.assertEqual(ISCSI_PORTS, ret)

    def test_get_target_iscsi_ports_with_no_ports(self):
        # Should raise an exception if there are no ports
        self.array.list_ports.return_value = []
        self.assertRaises(exception.PureDriverException,
                          self.driver._get_target_iscsi_ports)

    def test_get_target_iscsi_ports_with_only_fc_ports(self):
        # Should raise an exception of there are no iscsi ports
        self.array.list_ports.return_value = PORTS_WITHOUT
        self.assertRaises(exception.PureDriverException,
                          self.driver._get_target_iscsi_ports)

    @mock.patch("cinder.volume.utils.generate_password", autospec=True)
    @mock.patch(ISCSI_DRIVER_OBJ + "._get_host", autospec=True)
    @mock.patch(ISCSI_DRIVER_OBJ + "._generate_purity_host_name", spec=True)
    def test_connect(self, mock_generate, mock_host, mock_gen_secret):
        vol_name = VOLUME["name"] + "-cinder"
        result = {"vol": vol_name, "lun": 1}

        # Branch where host already exists
        mock_host.return_value = PURE_HOST
        self.array.connect_host.return_value = {"vol": vol_name, "lun": 1}
        real_result = self.driver._connect(VOLUME, ISCSI_CONNECTOR)
        self.assertEqual(result, real_result)
        mock_host.assert_called_with(self.driver, self.array, ISCSI_CONNECTOR)
        self.assertFalse(mock_generate.called)
        self.assertFalse(self.array.create_host.called)
        self.array.connect_host.assert_called_with(PURE_HOST_NAME, vol_name)

        # Branch where new host is created
        mock_host.return_value = None
        mock_generate.return_value = PURE_HOST_NAME
        real_result = self.driver._connect(VOLUME, ISCSI_CONNECTOR)
        mock_host.assert_called_with(self.driver, self.array, ISCSI_CONNECTOR)
        mock_generate.assert_called_with(HOSTNAME)
        self.array.create_host.assert_called_with(PURE_HOST_NAME,
                                                  iqnlist=[INITIATOR_IQN])
        self.assertEqual(result, real_result)

        mock_generate.reset_mock()
        self.array.reset_mock()
        self.assert_error_propagates(
            [mock_host, mock_generate, self.array.connect_host,
             self.array.create_host], self.driver._connect, VOLUME,
            ISCSI_CONNECTOR)

        self.mock_config.use_chap_auth = True
        chap_user = ISCSI_CONNECTOR["host"]
        chap_password = "sOmEseCr3t"

        # Branch where chap is used and credentials already exist
        initiator_data = [{"key": pure.CHAP_SECRET_KEY,
                           "value": chap_password}]
        self.mock_utils.get_driver_initiator_data.return_value = initiator_data
        self.driver._connect(VOLUME, ISCSI_CONNECTOR)
        result["auth_username"] = chap_user
        result["auth_password"] = chap_password
        self.assertDictEqual(result, real_result)
        self.array.set_host.assert_called_with(PURE_HOST_NAME,
                                               host_user=chap_user,
                                               host_password=chap_password)

        # Branch where chap is used and credentials are generated
        mock_gen_secret.return_value = chap_password
        self.mock_utils.get_driver_initiator_data.return_value = None
        self.driver._connect(VOLUME, ISCSI_CONNECTOR)
        result["auth_username"] = chap_user
        result["auth_password"] = chap_password

        self.assertDictEqual(result, real_result)
        self.array.set_host.assert_called_with(PURE_HOST_NAME,
                                               host_user=chap_user,
                                               host_password=chap_password)
        self.mock_utils.insert_driver_initiator_data.assert_called_with(
            ISCSI_CONNECTOR['initiator'],
            pure.CHAP_SECRET_KEY,
            chap_password
        )

    @mock.patch(ISCSI_DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_already_connected(self, mock_host):
        mock_host.return_value = PURE_HOST
        expected = {"host": PURE_HOST_NAME, "lun": 1}
        self.array.list_volume_private_connections.return_value = \
            [expected, {"host": "extra", "lun": 2}]
        self.array.connect_host.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=http_client.BAD_REQUEST,
                text="Connection already exists"
            )
        actual = self.driver._connect(VOLUME, ISCSI_CONNECTOR)
        self.assertEqual(expected, actual)
        self.assertTrue(self.array.connect_host.called)
        self.assertTrue(self.array.list_volume_private_connections)

    @mock.patch(ISCSI_DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_already_connected_list_hosts_empty(self, mock_host):
        mock_host.return_value = PURE_HOST
        self.array.list_volume_private_connections.return_value = {}
        self.array.connect_host.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=http_client.BAD_REQUEST,
                text="Connection already exists"
            )
        self.assertRaises(exception.PureDriverException, self.driver._connect,
                          VOLUME, ISCSI_CONNECTOR)
        self.assertTrue(self.array.connect_host.called)
        self.assertTrue(self.array.list_volume_private_connections)

    @mock.patch(ISCSI_DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_already_connected_list_hosts_exception(self, mock_host):
        mock_host.return_value = PURE_HOST
        self.array.list_volume_private_connections.side_effect = \
            self.purestorage_module.PureHTTPError(code=http_client.BAD_REQUEST,
                                                  text="")
        self.array.connect_host.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=http_client.BAD_REQUEST,
                text="Connection already exists"
            )
        self.assertRaises(self.purestorage_module.PureHTTPError,
                          self.driver._connect, VOLUME,
                          ISCSI_CONNECTOR)
        self.assertTrue(self.array.connect_host.called)
        self.assertTrue(self.array.list_volume_private_connections)

    @mock.patch(ISCSI_DRIVER_OBJ + "._get_chap_secret_from_init_data")
    @mock.patch(ISCSI_DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_host_deleted(self, mock_host, mock_get_secret):
        mock_host.return_value = None
        self.mock_config.use_chap_auth = True
        mock_get_secret.return_value = 'abcdef'

        self.array.set_host.side_effect = (
            self.purestorage_module.PureHTTPError(
                code=http_client.BAD_REQUEST, text='Host does not exist.'))

        # Because we mocked out retry make sure we are raising the right
        # exception to allow for retries to happen.
        self.assertRaises(exception.PureRetryableException,
                          self.driver._connect,
                          VOLUME, ISCSI_CONNECTOR)

    @mock.patch(ISCSI_DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_iqn_already_in_use(self, mock_host):
        mock_host.return_value = None

        self.array.create_host.side_effect = (
            self.purestorage_module.PureHTTPError(
                code=http_client.BAD_REQUEST,
                text='The specified IQN is already in use.'))

        # Because we mocked out retry make sure we are raising the right
        # exception to allow for retries to happen.
        self.assertRaises(exception.PureRetryableException,
                          self.driver._connect,
                          VOLUME, ISCSI_CONNECTOR)

    @mock.patch(ISCSI_DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_create_host_already_exists(self, mock_host):
        mock_host.return_value = None

        self.array.create_host.side_effect = (
            self.purestorage_module.PureHTTPError(
                code=http_client.BAD_REQUEST, text='Host already exists.'))

        # Because we mocked out retry make sure we are raising the right
        # exception to allow for retries to happen.
        self.assertRaises(exception.PureRetryableException,
                          self.driver._connect,
                          VOLUME, ISCSI_CONNECTOR)

    @mock.patch(ISCSI_DRIVER_OBJ + "._generate_chap_secret")
    def test_get_chap_credentials_create_new(self, mock_generate_secret):
        self.mock_utils.get_driver_initiator_data.return_value = []
        host = 'host1'
        expected_password = 'foo123'
        mock_generate_secret.return_value = expected_password
        self.mock_utils.insert_driver_initiator_data.return_value = True
        username, password = self.driver._get_chap_credentials(host,
                                                               INITIATOR_IQN)
        self.assertEqual(host, username)
        self.assertEqual(expected_password, password)
        self.mock_utils.insert_driver_initiator_data.assert_called_once_with(
            INITIATOR_IQN, pure.CHAP_SECRET_KEY, expected_password
        )

    @mock.patch(ISCSI_DRIVER_OBJ + "._generate_chap_secret")
    def test_get_chap_credentials_create_new_fail_to_set(self,
                                                         mock_generate_secret):
        host = 'host1'
        expected_password = 'foo123'
        mock_generate_secret.return_value = 'badpassw0rd'
        self.mock_utils.insert_driver_initiator_data.return_value = False
        self.mock_utils.get_driver_initiator_data.side_effect = [
            [],
            [{'key': pure.CHAP_SECRET_KEY, 'value': expected_password}],
            exception.PureDriverException(reason='this should never be hit'),
        ]

        username, password = self.driver._get_chap_credentials(host,
                                                               INITIATOR_IQN)
        self.assertEqual(host, username)
        self.assertEqual(expected_password, password)


class PureFCDriverTestCase(PureDriverTestCase):

    def setUp(self):
        super(PureFCDriverTestCase, self).setUp()
        self.driver = pure.PureFCDriver(configuration=self.mock_config)
        self.driver._array = self.array
        self.driver._lookup_service = mock.Mock()

    def test_get_host(self):
        good_host = PURE_HOST.copy()
        good_host.update(wwn=["another-wrong-wwn", INITIATOR_WWN])
        bad_host = {"name": "bad-host", "wwn": ["wrong-wwn"]}
        self.array.list_hosts.return_value = [bad_host]
        actual_result = self.driver._get_host(self.array, FC_CONNECTOR)
        self.assertIsNone(actual_result)
        self.array.list_hosts.return_value.append(good_host)
        actual_result = self.driver._get_host(self.array, FC_CONNECTOR)
        self.assertEqual(good_host, actual_result)
        self.assert_error_propagates([self.array.list_hosts],
                                     self.driver._get_host,
                                     self.array,
                                     FC_CONNECTOR)

    def test_get_host_uppercase_wwpn(self):
        expected_host = PURE_HOST.copy()
        expected_host['wwn'] = [INITIATOR_WWN]
        self.array.list_hosts.return_value = [expected_host]
        connector = FC_CONNECTOR.copy()
        connector['wwpns'] = [wwpn.upper() for wwpn in FC_CONNECTOR['wwpns']]

        actual_result = self.driver._get_host(self.array, connector)
        self.assertEqual(expected_host, actual_result)

    @mock.patch(FC_DRIVER_OBJ + "._connect")
    def test_initialize_connection(self, mock_connection):
        lookup_service = self.driver._lookup_service
        (lookup_service.get_device_mapping_from_network.
         return_value) = DEVICE_MAPPING
        mock_connection.return_value = {"vol": VOLUME["name"] + "-cinder",
                                        "lun": 1,
                                        }
        self.array.list_ports.return_value = FC_PORTS
        actual_result = self.driver.initialize_connection(VOLUME, FC_CONNECTOR)
        self.assertDictEqual(FC_CONNECTION_INFO, actual_result)

    @mock.patch(FC_DRIVER_OBJ + "._get_host", autospec=True)
    @mock.patch(FC_DRIVER_OBJ + "._generate_purity_host_name", spec=True)
    def test_connect(self, mock_generate, mock_host):
        vol_name = VOLUME["name"] + "-cinder"
        result = {"vol": vol_name, "lun": 1}

        # Branch where host already exists
        mock_host.return_value = PURE_HOST
        self.array.connect_host.return_value = {"vol": vol_name, "lun": 1}
        real_result = self.driver._connect(VOLUME, FC_CONNECTOR)
        self.assertEqual(result, real_result)
        mock_host.assert_called_with(self.driver, self.array, FC_CONNECTOR)
        self.assertFalse(mock_generate.called)
        self.assertFalse(self.array.create_host.called)
        self.array.connect_host.assert_called_with(PURE_HOST_NAME, vol_name)

        # Branch where new host is created
        mock_host.return_value = None
        mock_generate.return_value = PURE_HOST_NAME
        real_result = self.driver._connect(VOLUME, FC_CONNECTOR)
        mock_host.assert_called_with(self.driver, self.array, FC_CONNECTOR)
        mock_generate.assert_called_with(HOSTNAME)
        self.array.create_host.assert_called_with(PURE_HOST_NAME,
                                                  wwnlist={INITIATOR_WWN})
        self.assertEqual(result, real_result)

        mock_generate.reset_mock()
        self.array.reset_mock()
        self.assert_error_propagates(
            [mock_host, mock_generate, self.array.connect_host,
             self.array.create_host],
            self.driver._connect, VOLUME, FC_CONNECTOR)

    @mock.patch(FC_DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_already_connected(self, mock_host):
        mock_host.return_value = PURE_HOST
        expected = {"host": PURE_HOST_NAME, "lun": 1}
        self.array.list_volume_private_connections.return_value = \
            [expected, {"host": "extra", "lun": 2}]
        self.array.connect_host.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=http_client.BAD_REQUEST,
                text="Connection already exists"
            )
        actual = self.driver._connect(VOLUME, FC_CONNECTOR)
        self.assertEqual(expected, actual)
        self.assertTrue(self.array.connect_host.called)
        self.assertTrue(self.array.list_volume_private_connections)

    @mock.patch(FC_DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_already_connected_list_hosts_empty(self, mock_host):
        mock_host.return_value = PURE_HOST
        self.array.list_volume_private_connections.return_value = {}
        self.array.connect_host.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=http_client.BAD_REQUEST,
                text="Connection already exists"
            )
        self.assertRaises(exception.PureDriverException, self.driver._connect,
                          VOLUME, FC_CONNECTOR)
        self.assertTrue(self.array.connect_host.called)
        self.assertTrue(self.array.list_volume_private_connections)

    @mock.patch(FC_DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_already_connected_list_hosts_exception(self, mock_host):
        mock_host.return_value = PURE_HOST
        self.array.list_volume_private_connections.side_effect = \
            self.purestorage_module.PureHTTPError(code=http_client.BAD_REQUEST,
                                                  text="")
        self.array.connect_host.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=http_client.BAD_REQUEST,
                text="Connection already exists"
            )
        self.assertRaises(self.purestorage_module.PureHTTPError,
                          self.driver._connect, VOLUME, FC_CONNECTOR)
        self.assertTrue(self.array.connect_host.called)
        self.assertTrue(self.array.list_volume_private_connections)

    @mock.patch(FC_DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_wwn_already_in_use(self, mock_host):
        mock_host.return_value = None

        self.array.create_host.side_effect = (
            self.purestorage_module.PureHTTPError(
                code=http_client.BAD_REQUEST,
                text='The specified WWN is already in use.'))

        # Because we mocked out retry make sure we are raising the right
        # exception to allow for retries to happen.
        self.assertRaises(exception.PureRetryableException,
                          self.driver._connect,
                          VOLUME, FC_CONNECTOR)


@ddt.ddt
class PureVolumeUpdateStatsTestCase(PureBaseSharedDriverTestCase):
    def setUp(self):
        super(PureVolumeUpdateStatsTestCase, self).setUp()
        self.array.get.side_effect = self.fake_get_array

    @ddt.data(dict(used=10,
                   provisioned=100,
                   config_ratio=5,
                   expected_ratio=5,
                   auto=False),
              dict(used=10,
                   provisioned=100,
                   config_ratio=5,
                   expected_ratio=10,
                   auto=True),
              dict(used=0,
                   provisioned=100,
                   config_ratio=5,
                   expected_ratio=5,
                   auto=True),
              dict(used=10,
                   provisioned=0,
                   config_ratio=5,
                   expected_ratio=5,
                   auto=True))
    @ddt.unpack
    def test_get_thin_provisioning(self,
                                   used,
                                   provisioned,
                                   config_ratio,
                                   expected_ratio,
                                   auto):
        self.mock_config.pure_automatic_max_oversubscription_ratio = auto
        self.mock_config.max_over_subscription_ratio = config_ratio
        actual_ratio = self.driver._get_thin_provisioning(provisioned, used)
        self.assertEqual(expected_ratio, actual_ratio)

    @mock.patch(BASE_DRIVER_OBJ + '.get_goodness_function')
    @mock.patch(BASE_DRIVER_OBJ + '.get_filter_function')
    @mock.patch(BASE_DRIVER_OBJ + '._get_provisioned_space')
    @mock.patch(BASE_DRIVER_OBJ + '._get_thin_provisioning')
    def test_get_volume_stats(self, mock_get_thin_provisioning, mock_get_space,
                              mock_get_filter, mock_get_goodness):
        filter_function = 'capabilities.total_volumes < 10'
        goodness_function = '90'
        num_hosts = 20
        num_snaps = 175
        num_pgroups = 15
        reserved_percentage = 12

        self.array.list_hosts.return_value = [PURE_HOST] * num_hosts
        self.array.list_volumes.return_value = [PURE_SNAPSHOT] * num_snaps
        self.array.list_pgroups.return_value = [PURE_PGROUP] * num_pgroups
        self.mock_config.reserved_percentage = reserved_percentage
        mock_get_space.return_value = (PROVISIONED_CAPACITY * units.Gi, 100)
        mock_get_filter.return_value = filter_function
        mock_get_goodness.return_value = goodness_function
        mock_get_thin_provisioning.return_value = (PROVISIONED_CAPACITY /
                                                   USED_SPACE)

        expected_result = {
            'volume_backend_name': VOLUME_BACKEND_NAME,
            'vendor_name': 'Pure Storage',
            'driver_version': self.driver.VERSION,
            'storage_protocol': None,
            'consistencygroup_support': True,
            'thin_provisioning_support': True,
            'multiattach': False,
            'QoS_support': False,
            'total_capacity_gb': TOTAL_CAPACITY,
            'free_capacity_gb': TOTAL_CAPACITY - USED_SPACE,
            'reserved_percentage': reserved_percentage,
            'provisioned_capacity': PROVISIONED_CAPACITY,
            'max_over_subscription_ratio': (PROVISIONED_CAPACITY /
                                            USED_SPACE),
            'filter_function': filter_function,
            'goodness_function': goodness_function,
            'total_volumes': 100,
            'total_snapshots': num_snaps,
            'total_hosts': num_hosts,
            'total_pgroups': num_pgroups,
            'writes_per_sec': PERF_INFO['writes_per_sec'],
            'reads_per_sec': PERF_INFO['reads_per_sec'],
            'input_per_sec': PERF_INFO['input_per_sec'],
            'output_per_sec': PERF_INFO['output_per_sec'],
            'usec_per_read_op': PERF_INFO['usec_per_read_op'],
            'usec_per_write_op': PERF_INFO['usec_per_write_op'],
            'queue_depth': PERF_INFO['queue_depth'],
            'replication_enabled': False,
            'replication_type': ['async'],
            'replication_count': 0,
            'replication_targets': [],
        }

        real_result = self.driver.get_volume_stats(refresh=True)
        self.assertDictEqual(expected_result, real_result)

        # Make sure when refresh=False we are using cached values and not
        # sending additional requests to the array.
        self.array.reset_mock()
        real_result = self.driver.get_volume_stats(refresh=False)
        self.assertDictEqual(expected_result, real_result)
        self.assertFalse(self.array.get.called)
        self.assertFalse(self.array.list_volumes.called)
        self.assertFalse(self.array.list_hosts.called)
        self.assertFalse(self.array.list_pgroups.called)


class PureVolumeGroupsTestCase(PureBaseSharedDriverTestCase):
    def setUp(self):
        super(PureVolumeGroupsTestCase, self).setUp()
        self.array.get.side_effect = self.fake_get_array
        self.mock_context = mock.Mock()
        self.driver.db = mock.Mock()
        self.driver.db.group_get = mock.Mock()

    @mock.patch('cinder.db.group_get')
    @mock.patch(BASE_DRIVER_OBJ + '._add_volume_to_consistency_group')
    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_add_to_group_if_needed(self, mock_is_cg, mock_add_to_cg,
                                    mock_db_group_get):
        mock_is_cg.return_value = False
        vol_name = 'foo'
        group_id = fake.GROUP_ID
        volume = fake_volume.fake_volume_obj(None, group_id=group_id)
        group = mock.MagicMock()
        mock_db_group_get.return_value = group

        self.driver._add_to_group_if_needed(volume, vol_name)

        mock_is_cg.assert_called_once_with(group)
        mock_add_to_cg.assert_not_called()

    @mock.patch('cinder.db.group_get')
    @mock.patch(BASE_DRIVER_OBJ + '._add_volume_to_consistency_group')
    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_add_to_group_if_needed_with_cg(self, mock_is_cg, mock_add_to_cg,
                                            mock_db_group_get):
        mock_is_cg.return_value = True
        vol_name = 'foo'
        group_id = fake.GROUP_ID
        volume = fake_volume.fake_volume_obj(None, group_id=group_id)
        group = mock.MagicMock()
        mock_db_group_get.return_value = group

        self.driver._add_to_group_if_needed(volume, vol_name)

        mock_is_cg.assert_called_once_with(group)
        mock_add_to_cg.assert_called_once_with(
            group_id,
            vol_name
        )

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_create_group(self, mock_is_cg):
        mock_is_cg.return_value = False
        group = fake_group.fake_group_type_obj(None)
        self.assertRaises(
            NotImplementedError,
            self.driver.create_group,
            self.mock_context, group
        )
        mock_is_cg.assert_called_once_with(group)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_delete_group(self, mock_is_cg):
        mock_is_cg.return_value = False
        group = mock.MagicMock()
        volumes = [fake_volume.fake_volume_obj(None)]
        self.assertRaises(
            NotImplementedError,
            self.driver.delete_group,
            self.mock_context, group, volumes
        )
        mock_is_cg.assert_called_once_with(group)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_update_group(self, mock_is_cg):
        mock_is_cg.return_value = False
        group = mock.MagicMock()
        self.assertRaises(
            NotImplementedError,
            self.driver.update_group,
            self.mock_context, group
        )
        mock_is_cg.assert_called_once_with(group)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_create_group_from_src(self, mock_is_cg):
        mock_is_cg.return_value = False
        group = mock.MagicMock()
        volumes = [fake_volume.fake_volume_obj(None)]
        self.assertRaises(
            NotImplementedError,
            self.driver.create_group_from_src,
            self.mock_context, group, volumes
        )
        mock_is_cg.assert_called_once_with(group)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_create_group_snapshot(self, mock_is_cg):
        mock_is_cg.return_value = False
        group_snapshot = mock.MagicMock()
        snapshots = [fake_snapshot.fake_snapshot_obj(None)]
        self.assertRaises(
            NotImplementedError,
            self.driver.create_group_snapshot,
            self.mock_context, group_snapshot, snapshots
        )
        mock_is_cg.assert_called_once_with(group_snapshot)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_delete_group_snapshot(self, mock_is_cg):
        mock_is_cg.return_value = False
        group_snapshot = mock.MagicMock()
        snapshots = [fake_snapshot.fake_snapshot_obj(None)]
        self.assertRaises(
            NotImplementedError,
            self.driver.create_group_snapshot,
            self.mock_context, group_snapshot, snapshots
        )
        mock_is_cg.assert_called_once_with(group_snapshot)

    @mock.patch(BASE_DRIVER_OBJ + '.create_consistencygroup')
    @mock.patch('cinder.volume.group_types.get_group_type_specs')
    def test_create_group_with_cg(self, mock_get_specs, mock_create_cg):
        mock_get_specs.return_value = '<is> True'
        group = mock.MagicMock()
        self.driver.create_group(self.mock_context, group)
        mock_create_cg.assert_called_once_with(self.mock_context, group)

    @mock.patch(BASE_DRIVER_OBJ + '.delete_consistencygroup')
    @mock.patch('cinder.volume.group_types.get_group_type_specs')
    def test_delete_group_with_cg(self, mock_get_specs, mock_delete_cg):
        mock_get_specs.return_value = '<is> True'
        group = mock.MagicMock()
        volumes = [fake_volume.fake_volume_obj(None)]
        self.driver.delete_group(self.mock_context, group, volumes)
        mock_delete_cg.assert_called_once_with(self.mock_context,
                                               group,
                                               volumes)

    @mock.patch(BASE_DRIVER_OBJ + '.update_consistencygroup')
    @mock.patch('cinder.volume.group_types.get_group_type_specs')
    def test_update_group_with_cg(self, mock_get_specs, mock_update_cg):
        mock_get_specs.return_value = '<is> True'
        group = mock.MagicMock()
        addvollist = [mock.Mock()]
        remvollist = [mock.Mock()]
        self.driver.update_group(
            self.mock_context,
            group,
            addvollist,
            remvollist
        )
        mock_update_cg.assert_called_once_with(
            self.mock_context,
            group,
            addvollist,
            remvollist
        )

    @mock.patch(BASE_DRIVER_OBJ + '.create_consistencygroup_from_src')
    @mock.patch('cinder.volume.group_types.get_group_type_specs')
    def test_create_group_from_src_with_cg(self, mock_get_specs, mock_create):
        mock_get_specs.return_value = '<is> True'
        group = mock.MagicMock()
        volumes = [mock.Mock()]
        group_snapshot = mock.Mock()
        snapshots = [mock.Mock()]
        source_group = mock.MagicMock()
        source_vols = [mock.Mock()]

        self.driver.create_group_from_src(
            self.mock_context,
            group,
            volumes,
            group_snapshot,
            snapshots,
            source_group,
            source_vols
        )
        mock_create.assert_called_once_with(
            self.mock_context,
            group,
            volumes,
            group_snapshot,
            snapshots,
            source_group,
            source_vols
        )

    @mock.patch(BASE_DRIVER_OBJ + '.create_cgsnapshot')
    @mock.patch('cinder.volume.group_types.get_group_type_specs')
    def test_create_group_snapshot_with_cg(self, mock_get_specs,
                                           mock_create_cgsnap):
        mock_get_specs.return_value = '<is> True'
        group_snapshot = mock.MagicMock()
        snapshots = [mock.Mock()]

        self.driver.create_group_snapshot(
            self.mock_context,
            group_snapshot,
            snapshots
        )
        mock_create_cgsnap.assert_called_once_with(
            self.mock_context,
            group_snapshot,
            snapshots
        )

    @mock.patch(BASE_DRIVER_OBJ + '.delete_cgsnapshot')
    @mock.patch('cinder.volume.group_types.get_group_type_specs')
    def test_delete_group_snapshot_with_cg(self, mock_get_specs,
                                           mock_delete_cg):
        mock_get_specs.return_value = '<is> True'
        group_snapshot = mock.MagicMock()
        snapshots = [mock.Mock()]

        self.driver.delete_group_snapshot(
            self.mock_context,
            group_snapshot,
            snapshots
        )
        mock_delete_cg.assert_called_once_with(
            self.mock_context,
            group_snapshot,
            snapshots
        )
