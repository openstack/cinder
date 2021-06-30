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
import http
import sys
from unittest import mock

import ddt
from oslo_utils import units

from cinder import exception
from cinder.objects import fields
from cinder.objects import volume_type
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_group
from cinder.tests.unit import fake_group_snapshot
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit import test
from cinder.volume import qos_specs
from cinder.volume import volume_types
from cinder.volume import volume_utils


def fake_retry(exceptions, interval=1, retries=3, backoff_rate=2):
    def _decorator(f):
        return f
    return _decorator


patch_retry = mock.patch('cinder.utils.retry', fake_retry)
patch_retry.start()
sys.modules['purestorage'] = mock.Mock()
from cinder.volume.drivers import pure  # noqa

# Only mock utils.retry for cinder.volume.drivers.pure import
patch_retry.stop()

DRIVER_PATH = "cinder.volume.drivers.pure"
BASE_DRIVER_OBJ = DRIVER_PATH + ".PureBaseVolumeDriver"
ISCSI_DRIVER_OBJ = DRIVER_PATH + ".PureISCSIDriver"
FC_DRIVER_OBJ = DRIVER_PATH + ".PureFCDriver"
ARRAY_OBJ = DRIVER_PATH + ".FlashArray"
UNMANAGED_SUFFIX = "-unmanaged"

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
# These two IP blocks should use the same prefix (see ISCSI_CIDR_FILTERED to
# make sure changes make sense). Our arrays now have 4 IPv4 + 4 IPv6 ports.
ISCSI_IPS = ["10.0.0." + str(i + 1) for i in range(len(ISCSI_PORT_NAMES))]
ISCSI_IPS += ["[2001:db8::" + str(i + 1) + "]"
              for i in range(len(ISCSI_PORT_NAMES))]
AC_ISCSI_IPS = ["10.0.0." + str(i + 1 + len(ISCSI_PORT_NAMES))
                for i in range(len(ISCSI_PORT_NAMES))]
AC_ISCSI_IPS += ["[2001:db8::1:" + str(i + 1) + "]"
                 for i in range(len(ISCSI_PORT_NAMES))]
ISCSI_CIDR = "0.0.0.0/0"
ISCSI_CIDR_V6 = "::/0"
# Designed to filter out only one of the AC ISCSI IPs, leaving the rest in
ISCSI_CIDR_FILTERED = '10.0.0.0/29'
# Include several IP / networks: 10.0.0.2, 10.0.0.3, 10.0.0.6, 10.0.0.7
ISCSI_CIDRS_FILTERED = ['10.0.0.2', '10.0.0.3', '2001:db8::1:2/127']
FC_WWNS = ["21000024ff59fe9" + str(i + 1) for i in range(len(FC_PORT_NAMES))]
AC_FC_WWNS = [
    "21000024ff59fab" + str(i + 1) for i in range(len(FC_PORT_NAMES))]
HOSTNAME = "computenode1"
PURE_HOST_NAME = pure.PureBaseVolumeDriver._generate_purity_host_name(HOSTNAME)
PURE_HOST = {
    "name": PURE_HOST_NAME,
    "hgroup": None,
    "iqn": [],
    "wwn": [],
}
INITIATOR_IQN = "iqn.1993-08.org.debian:01:222"
INITIATOR_WWN = "5001500150015081abc"
ISCSI_CONNECTOR = {"initiator": INITIATOR_IQN, "host": HOSTNAME}
FC_CONNECTOR = {"wwpns": {INITIATOR_WWN}, "host": HOSTNAME}
TARGET_IQN = "iqn.2010-06.com.purestorage:flasharray.12345abc"
AC_TARGET_IQN = "iqn.2018-06.com.purestorage:flasharray.67890def"
TARGET_WWN = "21000024ff59fe94"
TARGET_PORT = "3260"
INITIATOR_TARGET_MAP = {
    # _build_initiator_target_map() calls list(set()) on the list,
    # we must also call list(set()) to get the exact same order
    '5001500150015081abc': list(set(FC_WWNS)),
}
AC_INITIATOR_TARGET_MAP = {
    # _build_initiator_target_map() calls list(set()) on the list,
    # we must also call list(set()) to get the exact same order
    '5001500150015081abc': list(set(FC_WWNS + AC_FC_WWNS)),
}
DEVICE_MAPPING = {
    "fabric": {
        'initiator_port_wwn_list': {INITIATOR_WWN},
        'target_port_wwn_list': FC_WWNS,
    },
}
AC_DEVICE_MAPPING = {
    "fabric": {
        'initiator_port_wwn_list': {INITIATOR_WWN},
        'target_port_wwn_list': FC_WWNS + AC_FC_WWNS,
    },
}

# We now have IPv6 in addition to IPv4 on each interface
ISCSI_PORTS = [{"name": name,
                "iqn": TARGET_IQN,
                "portal": ip + ":" + TARGET_PORT,
                "wwn": None,
                } for name, ip in zip(ISCSI_PORT_NAMES * 2, ISCSI_IPS)]
AC_ISCSI_PORTS = [{"name": name,
                   "iqn": AC_TARGET_IQN,
                   "portal": ip + ":" + TARGET_PORT,
                   "wwn": None,
                   } for name, ip in zip(ISCSI_PORT_NAMES * 2, AC_ISCSI_IPS)]
FC_PORTS = [{"name": name,
             "iqn": None,
             "portal": None,
             "wwn": wwn,
             } for name, wwn in zip(FC_PORT_NAMES, FC_WWNS)]
AC_FC_PORTS = [{"name": name,
                "iqn": None,
                "portal": None,
                "wwn": wwn,
                } for name, wwn in zip(FC_PORT_NAMES, AC_FC_WWNS)]
NON_ISCSI_PORT = {
    "name": "ct0.fc1",
    "iqn": None,
    "portal": None,
    "wwn": "5001500150015081",
}
PORTS_WITH = ISCSI_PORTS + [NON_ISCSI_PORT]
PORTS_WITHOUT = [NON_ISCSI_PORT]
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
        "wwn": "3624a93709714b5cb91634c470002b2c8",
    },
}
ISCSI_CONNECTION_INFO_V6 = {
    "driver_volume_type": "iscsi",
    "data": {
        "target_discovered": False,
        "discard": True,
        "target_luns": [1, 1, 1, 1],
        "target_iqns": [TARGET_IQN, TARGET_IQN, TARGET_IQN, TARGET_IQN],
        "target_portals": [ISCSI_IPS[4] + ":" + TARGET_PORT,
                           ISCSI_IPS[5] + ":" + TARGET_PORT,
                           ISCSI_IPS[6] + ":" + TARGET_PORT,
                           ISCSI_IPS[7] + ":" + TARGET_PORT],
        "wwn": "3624a93709714b5cb91634c470002b2c8",
    },
}
ISCSI_CONNECTION_INFO_AC = {
    "driver_volume_type": "iscsi",
    "data": {
        "target_discovered": False,
        "discard": True,
        "target_luns": [1, 1, 1, 1, 5, 5, 5, 5],
        "target_iqns": [TARGET_IQN, TARGET_IQN,
                        TARGET_IQN, TARGET_IQN,
                        AC_TARGET_IQN, AC_TARGET_IQN,
                        AC_TARGET_IQN, AC_TARGET_IQN],
        "target_portals": [ISCSI_IPS[0] + ":" + TARGET_PORT,
                           ISCSI_IPS[1] + ":" + TARGET_PORT,
                           ISCSI_IPS[2] + ":" + TARGET_PORT,
                           ISCSI_IPS[3] + ":" + TARGET_PORT,
                           AC_ISCSI_IPS[0] + ":" + TARGET_PORT,
                           AC_ISCSI_IPS[1] + ":" + TARGET_PORT,
                           AC_ISCSI_IPS[2] + ":" + TARGET_PORT,
                           AC_ISCSI_IPS[3] + ":" + TARGET_PORT],
        "wwn": "3624a93709714b5cb91634c470002b2c8",
    },
}
ISCSI_CONNECTION_INFO_AC_FILTERED = {
    "driver_volume_type": "iscsi",
    "data": {
        "target_discovered": False,
        "discard": True,
        "target_luns": [1, 1, 1, 1, 5, 5, 5],
        # Final entry filtered by ISCSI_CIDR_FILTERED
        "target_iqns": [TARGET_IQN, TARGET_IQN,
                        TARGET_IQN, TARGET_IQN,
                        AC_TARGET_IQN, AC_TARGET_IQN,
                        AC_TARGET_IQN],
        # Final entry filtered by ISCSI_CIDR_FILTERED
        "target_portals": [ISCSI_IPS[0] + ":" + TARGET_PORT,
                           ISCSI_IPS[1] + ":" + TARGET_PORT,
                           ISCSI_IPS[2] + ":" + TARGET_PORT,
                           ISCSI_IPS[3] + ":" + TARGET_PORT,
                           AC_ISCSI_IPS[0] + ":" + TARGET_PORT,
                           AC_ISCSI_IPS[1] + ":" + TARGET_PORT,
                           AC_ISCSI_IPS[2] + ":" + TARGET_PORT],
        "wwn": "3624a93709714b5cb91634c470002b2c8",
    },
}
ISCSI_CONNECTION_INFO_AC_FILTERED_LIST = {
    "driver_volume_type": "iscsi",
    "data": {
        "target_discovered": False,
        "discard": True,
        "target_luns": [1, 1, 5, 5],
        # Final entry filtered by ISCSI_CIDR_FILTERED
        "target_iqns": [TARGET_IQN, TARGET_IQN,
                        AC_TARGET_IQN, AC_TARGET_IQN],
        # Final entry filtered by ISCSI_CIDR_FILTERED
        "target_portals": [ISCSI_IPS[1] + ":" + TARGET_PORT,
                           ISCSI_IPS[2] + ":" + TARGET_PORT,
                           AC_ISCSI_IPS[5] + ":" + TARGET_PORT,   # IPv6
                           AC_ISCSI_IPS[6] + ":" + TARGET_PORT],  # IPv6
        "wwn": "3624a93709714b5cb91634c470002b2c8",
    },
}

FC_CONNECTION_INFO = {
    "driver_volume_type": "fibre_channel",
    "data": {
        "target_wwn": FC_WWNS,
        "target_wwns": FC_WWNS,
        "target_lun": 1,
        "target_luns": [1, 1, 1, 1],
        "target_discovered": True,
        "initiator_target_map": INITIATOR_TARGET_MAP,
        "discard": True,
        "wwn": "3624a93709714b5cb91634c470002b2c8",
    },
}
FC_CONNECTION_INFO_AC = {
    "driver_volume_type": "fibre_channel",
    "data": {
        "target_wwn": FC_WWNS + AC_FC_WWNS,
        "target_wwns": FC_WWNS + AC_FC_WWNS,
        "target_lun": 1,
        "target_luns": [1, 1, 1, 1, 5, 5, 5, 5],
        "target_discovered": True,
        "initiator_target_map": AC_INITIATOR_TARGET_MAP,
        "discard": True,
        "wwn": "3624a93709714b5cb91634c470002b2c8",
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
    fake_volume.fake_volume_obj(
        None, id=fake.VOLUME_ID,
        provider_id=("volume-%s-cinder" % fake.VOLUME_ID)
    ),
    fake_volume.fake_volume_obj(
        None, id=fake.VOLUME2_ID,
        provider_id=("volume-%s-cinder" % fake.VOLUME2_ID)
    ),
    fake_volume.fake_volume_obj(
        None, id=fake.VOLUME3_ID,
        provider_id=("volume-%s-cinder" % fake.VOLUME3_ID)
    ),
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

CINDER_POD = {
    'arrays': [
        {
            'status': 'online',
            'array_id': '47966b2d-a1ed-4144-8cae-6332794562b8',
            'name': 'fs83-14',
            'mediator_status': 'online'
        },
        {
            'status': 'online',
            'array_id': '8ed17cf4-4650-4634-ab3d-f2ca165cd021',
            'name': 'fs83-15',
            'mediator_status': 'online'
        }
    ],
    'source': None,
    'name': 'cinder-pod'
}

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
        'reason_not_safe': '',
        'cinder_id': None,
        'extra_info': None,
    },
    {
        'reference': {'name': 'myVol2'},
        'size': 3,
        'safe_to_manage': True,
        'reason_not_safe': '',
        'cinder_id': None,
        'extra_info': None,
    },
    {
        'reference': {'name': 'myVol3'},
        'size': 3,
        'safe_to_manage': True,
        'reason_not_safe': '',
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
MAX_SNAP_LENGTH = 96

# unit for maxBWS is MB
QOS_IOPS_BWS = {"maxIOPS": "100", "maxBWS": "1"}
QOS_IOPS_BWS_2 = {"maxIOPS": "1000", "maxBWS": "10"}
QOS_INVALID = {"maxIOPS": "100", "maxBWS": str(512 * 1024 + 1)}
QOS_ZEROS = {"maxIOPS": "0", "maxBWS": "0"}
QOS_IOPS = {"maxIOPS": "100"}
QOS_BWS = {"maxBWS": "1"}


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
        self.mock_config.pure_iscsi_cidr = ISCSI_CIDR
        self.mock_config.pure_iscsi_cidr_list = None
        self.array = mock.Mock()
        self.array.get.return_value = GET_ARRAY_PRIMARY
        self.array.array_name = GET_ARRAY_PRIMARY["array_name"]
        self.array.array_id = GET_ARRAY_PRIMARY["id"]
        self.async_array2 = mock.Mock()
        self.async_array2.array_name = GET_ARRAY_SECONDARY["array_name"]
        self.async_array2.array_id = GET_ARRAY_SECONDARY["id"]
        self.async_array2.get.return_value = GET_ARRAY_SECONDARY
        self.async_array2.replication_type = 'async'
        self.purestorage_module = pure.purestorage
        self.purestorage_module.VERSION = '1.4.0'
        self.purestorage_module.PureHTTPError = FakePureStorageHTTPError

    def fake_get_array(self, *args, **kwargs):
        if 'action' in kwargs and kwargs['action'] == 'monitor':
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
            mock_func.side_effect = [pure.PureDriverException(
                reason='reason')]
            self.assertRaises(pure.PureDriverException,
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
        self.driver._replication_pod_name = 'cinder-pod'
        self.driver._replication_pg_name = 'cinder-group'
        self.array._list_available_rest_versions.return_value = [
            '1.0', '1.1', '1.2', '1.3', '1.4', '1.5', '1.6', '1.7', '1.8',
            '1.9', '1.10', '1.11', '1.12', '1.13', '1.14', '1.15', '1.16',
            '1.17', '1.18', '1.19']
        self.purestorage_module.FlashArray.side_effect = None
        self.async_array2._list_available_rest_versions.return_value = [
            '1.0', '1.1', '1.2', '1.3', '1.4', '1.5', '1.6', '1.7', '1.8',
            '1.9', '1.10', '1.11', '1.12', '1.13', '1.14', '1.15', '1.16',
            '1.17', '1.18', '1.19']

    def new_fake_vol(self, set_provider_id=True, fake_context=None,
                     spec=None, type_extra_specs=None, type_qos_specs_id=None,
                     type_qos_specs=None):
        if fake_context is None:
            fake_context = mock.MagicMock()
        if type_extra_specs is None:
            type_extra_specs = {}
        if spec is None:
            spec = {}

        voltype = fake_volume.fake_volume_type_obj(fake_context)
        voltype.extra_specs = type_extra_specs
        voltype.qos_specs_id = type_qos_specs_id
        voltype.qos_specs = type_qos_specs

        vol = fake_volume.fake_volume_obj(fake_context, **spec)

        repl_type = self.driver._get_replication_type_from_vol_type(voltype)
        vol_name = vol.name + '-cinder'
        if repl_type == 'sync':
            vol_name = 'cinder-pod::' + vol_name

        if set_provider_id:
            vol.provider_id = vol_name

        vol.volume_type = voltype
        vol.volume_type_id = voltype.id
        vol.volume_attachment = None

        return vol, vol_name

    def new_fake_snap(self, vol=None, group_snap=None):
        if vol:
            vol_name = vol.name + "-cinder"
        else:
            vol, vol_name = self.new_fake_vol()
        snap = fake_snapshot.fake_snapshot_obj(mock.MagicMock())
        snap.volume_id = vol.id
        snap.volume = vol

        if group_snap is not None:
            snap.group_snapshot_id = group_snap.id
            snap.group_snapshot = group_snap

        snap_name = "%s.%s" % (vol_name, snap.name)
        return snap, snap_name

    def new_fake_group(self):
        group = fake_group.fake_group_obj(mock.MagicMock())
        group_name = "consisgroup-%s-cinder" % group.id
        return group, group_name

    def new_fake_group_snap(self, group=None):
        if group:
            group_name = "consisgroup-%s-cinder" % group.id
        else:
            group, group_name = self.new_fake_group()
        group_snap = fake_group_snapshot.fake_group_snapshot_obj(
            mock.MagicMock())

        group_snap_name = "%s.cgsnapshot-%s-cinder" % (group_name,
                                                       group_snap.id)

        group_snap.group = group
        group_snap.group_id = group.id

        return group_snap, group_snap_name


@ddt.ddt(testNameFormat=ddt.TestNameFormat.INDEX_ONLY)
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

        self.mock_config.pure_replication_pg_name = 'cinder-group'
        self.mock_config.pure_replication_pod_name = 'cinder-pod'
        self.mock_config.safe_get.return_value = [
            {"backend_id": self.driver._array.array_id,
             "managed_backend_name": None,
             "san_ip": "1.2.3.4",
             "api_token": "abc123"}]

    @mock.patch(BASE_DRIVER_OBJ + '._generate_replication_retention')
    @mock.patch(BASE_DRIVER_OBJ + '._setup_replicated_pgroups')
    def test_parse_replication_configs_single_async_target(
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
                         only_target_array.backend_id)

    @mock.patch(BASE_DRIVER_OBJ + '._generate_replication_retention')
    @mock.patch(BASE_DRIVER_OBJ + '._setup_replicated_pgroups')
    def test_parse_replication_configs_multiple_async_target(
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
            [self.array, self.async_array2]
        self.driver.parse_replication_configs()
        self.assertEqual(2, len(self.driver._replication_target_arrays))
        self.assertEqual(self.array, self.driver._replication_target_arrays[0])
        first_target_array = self.driver._replication_target_arrays[0]
        self.assertEqual(GET_ARRAY_PRIMARY["id"],
                         first_target_array.backend_id)
        self.assertEqual(
            self.async_array2, self.driver._replication_target_arrays[1])
        second_target_array = self.driver._replication_target_arrays[1]
        self.assertEqual(GET_ARRAY_SECONDARY["id"],
                         second_target_array.backend_id)

    @mock.patch(BASE_DRIVER_OBJ + '._generate_replication_retention')
    @mock.patch(BASE_DRIVER_OBJ + '._setup_replicated_pgroups')
    def test_parse_replication_configs_single_sync_target_non_uniform(
            self,
            mock_setup_repl_pgroups,
            mock_generate_replication_retention):
        retention = mock.MagicMock()
        mock_generate_replication_retention.return_value = retention
        mock_setup_repl_pgroups.return_value = None

        # Test single array configured
        self.mock_config.safe_get.return_value = [
            {
                "backend_id": "foo",
                "managed_backend_name": None,
                "san_ip": "1.2.3.4",
                "api_token": "abc123",
                "type": "sync",
            }
        ]
        mock_target = mock.MagicMock()
        mock_target.get.return_value = GET_ARRAY_PRIMARY
        mock_target._list_available_rest_versions.return_value = [
            '1.0', '1.1', '1.2', '1.3', '1.4', '1.5', '1.6', '1.7', '1.8',
            '1.9', '1.10', '1.11', '1.12', '1.13', '1.14', '1.15', '1.16',
            '1.17', '1.18', '1.19']

        self.purestorage_module.FlashArray.return_value = mock_target
        self.driver.parse_replication_configs()
        self.assertEqual(1, len(self.driver._replication_target_arrays))
        self.assertEqual(mock_target,
                         self.driver._replication_target_arrays[0])
        only_target_array = self.driver._replication_target_arrays[0]
        self.assertEqual("foo", only_target_array.backend_id)
        self.assertEqual([mock_target],
                         self.driver._active_cluster_target_arrays)
        self.assertEqual(
            0, len(self.driver._uniform_active_cluster_target_arrays))

    @mock.patch(BASE_DRIVER_OBJ + '._generate_replication_retention')
    @mock.patch(BASE_DRIVER_OBJ + '._setup_replicated_pgroups')
    def test_parse_replication_configs_single_sync_target_uniform(
            self,
            mock_setup_repl_pgroups,
            mock_generate_replication_retention):
        retention = mock.MagicMock()
        mock_generate_replication_retention.return_value = retention
        mock_setup_repl_pgroups.return_value = None

        # Test single array configured
        self.mock_config.safe_get.return_value = [
            {
                "backend_id": "foo",
                "managed_backend_name": None,
                "san_ip": "1.2.3.4",
                "api_token": "abc123",
                "type": "sync",
                "uniform": True,
            }
        ]
        mock_target = mock.MagicMock()
        mock_target.get.return_value = GET_ARRAY_PRIMARY
        mock_target._list_available_rest_versions.return_value = [
            '1.0', '1.1', '1.2', '1.3', '1.4', '1.5', '1.6', '1.7', '1.8',
            '1.9', '1.10', '1.11', '1.12', '1.13', '1.14', '1.15', '1.16',
            '1.17', '1.18', '1.19']

        self.purestorage_module.FlashArray.return_value = mock_target
        self.driver.parse_replication_configs()
        self.assertEqual(1, len(self.driver._replication_target_arrays))
        self.assertEqual(mock_target,
                         self.driver._replication_target_arrays[0])
        only_target_array = self.driver._replication_target_arrays[0]
        self.assertEqual("foo", only_target_array.backend_id)
        self.assertEqual([mock_target],
                         self.driver._active_cluster_target_arrays)
        self.assertEqual(
            1, len(self.driver._uniform_active_cluster_target_arrays))
        self.assertEqual(
            mock_target, self.driver._uniform_active_cluster_target_arrays[0])

    @mock.patch(BASE_DRIVER_OBJ + '._generate_replication_retention')
    @mock.patch(BASE_DRIVER_OBJ + '._setup_replicated_pgroups')
    def test_do_setup_replicated(self,
                                 mock_setup_repl_pgroups,
                                 mock_generate_replication_retention):
        retention = mock.MagicMock()
        mock_generate_replication_retention.return_value = retention
        self._setup_mocks_for_replication()
        self.async_array2.get.return_value = GET_ARRAY_SECONDARY
        self.array.get.return_value = GET_ARRAY_PRIMARY
        self.purestorage_module.FlashArray.side_effect = [self.array,
                                                          self.async_array2]
        self.driver.do_setup(None)
        self.assertEqual(self.array, self.driver._array)
        self.assertEqual(1, len(self.driver._replication_target_arrays))
        self.assertEqual(self.async_array2,
                         self.driver._replication_target_arrays[0])
        calls = [
            mock.call(self.array, [self.async_array2], 'cinder-group',
                      REPLICATION_INTERVAL_IN_SEC, retention)
        ]
        mock_setup_repl_pgroups.assert_has_calls(calls)

    @mock.patch(BASE_DRIVER_OBJ + '._setup_replicated_pods')
    @mock.patch(BASE_DRIVER_OBJ + '._generate_replication_retention')
    @mock.patch(BASE_DRIVER_OBJ + '._setup_replicated_pgroups')
    def test_do_setup_replicated_sync_rep(self,
                                          mock_setup_repl_pgroups,
                                          mock_generate_replication_retention,
                                          mock_setup_pods):
        retention = mock.MagicMock()
        mock_generate_replication_retention.return_value = retention
        self._setup_mocks_for_replication()

        self.mock_config.safe_get.return_value = [
            {
                "backend_id": "foo",
                "managed_backend_name": None,
                "san_ip": "1.2.3.4",
                "api_token": "abc123",
                "type": "sync",
            }
        ]
        mock_sync_target = mock.MagicMock()
        mock_sync_target.get.return_value = GET_ARRAY_SECONDARY
        mock_sync_target._list_available_rest_versions.return_value = [
            '1.0', '1.1', '1.2', '1.3', '1.4', '1.5', '1.6', '1.7', '1.8',
            '1.9', '1.10', '1.11', '1.12', '1.13', '1.14', '1.15', '1.16',
            '1.17', '1.18', '1.19']
        self.array.get.return_value = GET_ARRAY_PRIMARY
        self.array._list_available_rest_versions.return_value = [
            '1.0', '1.1', '1.2', '1.3', '1.4', '1.5', '1.6', '1.7', '1.8',
            '1.9', '1.10', '1.11', '1.12', '1.13', '1.14', '1.15', '1.16',
            '1.17', '1.18', '1.19']
        self.purestorage_module.FlashArray.side_effect = [self.array,
                                                          mock_sync_target]
        self.driver.do_setup(None)
        self.assertEqual(self.array, self.driver._array)

        mock_setup_repl_pgroups.assert_has_calls([
            mock.call(self.array, [mock_sync_target], 'cinder-group',
                      REPLICATION_INTERVAL_IN_SEC, retention),
        ])
        mock_setup_pods.assert_has_calls([
            mock.call(self.array, [mock_sync_target], 'cinder-pod')
        ])

    def test_update_provider_info_update_all(self):
        test_vols = [
            self.new_fake_vol(spec={'id': fake.VOLUME_ID},
                              set_provider_id=False),
            self.new_fake_vol(spec={'id': fake.VOLUME2_ID},
                              set_provider_id=False),
            self.new_fake_vol(spec={'id': fake.VOLUME3_ID},
                              set_provider_id=False),
        ]

        vols = []
        vol_names = []
        for v in test_vols:
            vols.append(v[0])
            vol_names.append(v[1])

        model_updates, _ = self.driver.update_provider_info(vols, None)
        self.assertEqual(len(test_vols), len(model_updates))
        for update, vol_name in zip(model_updates, vol_names):
            self.assertEqual(vol_name, update['provider_id'])

    def test_update_provider_info_update_some(self):
        test_vols = [
            self.new_fake_vol(spec={'id': fake.VOLUME_ID},
                              set_provider_id=True),
            self.new_fake_vol(spec={'id': fake.VOLUME2_ID},
                              set_provider_id=True),
            self.new_fake_vol(spec={'id': fake.VOLUME3_ID},
                              set_provider_id=False),
        ]

        vols = []
        vol_names = []
        for v in test_vols:
            vols.append(v[0])
            vol_names.append(v[1])

        model_updates, _ = self.driver.update_provider_info(vols, None)
        self.assertEqual(1, len(model_updates))
        self.assertEqual(vol_names[2], model_updates[0]['provider_id'])

    def test_update_provider_info_no_updates(self):
        test_vols = [
            self.new_fake_vol(spec={'id': fake.VOLUME_ID},
                              set_provider_id=True),
            self.new_fake_vol(spec={'id': fake.VOLUME2_ID},
                              set_provider_id=True),
            self.new_fake_vol(spec={'id': fake.VOLUME3_ID},
                              set_provider_id=True),
        ]

        vols = []
        for v in test_vols:
            vols.append(v[0])

        model_updates, _ = self.driver.update_provider_info(vols, None)
        self.assertEqual(0, len(model_updates))

    def test_generate_purity_host_name(self):
        result = self.driver._generate_purity_host_name(
            "really-long-string-thats-a-bit-too-long")
        self.assertTrue(result.startswith("really-long-string-that-"))
        self.assertTrue(result.endswith("-cinder"))
        self.assertEqual(63, len(result))
        self.assertTrue(bool(pure.GENERATED_NAME.match(result)))
        result = self.driver._generate_purity_host_name("!@#$%^-invalid&*")
        self.assertTrue(result.startswith("invalid---"))
        self.assertTrue(result.endswith("-cinder"))
        self.assertEqual(49, len(result))
        self.assertIsNotNone(pure.GENERATED_NAME.match(result))

    def test_revert_to_snapshot(self):
        vol, vol_name = self.new_fake_vol(set_provider_id=True)
        snap, snap_name = self.new_fake_snap(vol)

        context = mock.MagicMock()
        self.driver.revert_to_snapshot(context, vol, snap)

        self.array.copy_volume.assert_called_with(snap_name, vol_name,
                                                  overwrite=True)
        self.assert_error_propagates([self.array.copy_volume],
                                     self.driver.revert_to_snapshot,
                                     context, vol, snap)

    def test_revert_to_snapshot_group(self):
        vol, vol_name = self.new_fake_vol(set_provider_id=True)
        group, group_name = self.new_fake_group()
        group_snap, group_snap_name = self.new_fake_group_snap(group)
        snap, snap_name = self.new_fake_snap(vol, group_snap)

        copy_vol_name = "%s.%s" % (group_snap_name, vol_name)

        context = mock.MagicMock()
        self.driver.revert_to_snapshot(context, vol, snap)

        self.array.copy_volume.assert_called_with(copy_vol_name, vol_name,
                                                  overwrite=True)

        self.assert_error_propagates([self.array.copy_volume],
                                     self.driver.revert_to_snapshot,
                                     context, vol, snap)

    @mock.patch(BASE_DRIVER_OBJ + "._add_to_group_if_needed")
    @mock.patch(BASE_DRIVER_OBJ + "._get_replication_type_from_vol_type")
    def test_create_volume(self, mock_get_repl_type, mock_add_to_group):
        mock_get_repl_type.return_value = None
        vol_obj = fake_volume.fake_volume_obj(mock.MagicMock(), size=2)
        self.driver.create_volume(vol_obj)
        vol_name = vol_obj["name"] + "-cinder"
        self.array.create_volume.assert_called_with(
            vol_name, 2 * units.Gi)
        mock_add_to_group.assert_called_once_with(vol_obj,
                                                  vol_name)
        self.assert_error_propagates([self.array.create_volume],
                                     self.driver.create_volume, vol_obj)

    @mock.patch(BASE_DRIVER_OBJ + "._add_to_group_if_needed")
    @mock.patch(BASE_DRIVER_OBJ + "._get_replication_type_from_vol_type")
    @mock.patch.object(volume_types, 'get_volume_type')
    def test_create_volume_from_snapshot(self, mock_get_volume_type,
                                         mock_get_replicated_type,
                                         mock_add_to_group):
        srcvol, _ = self.new_fake_vol()
        snap = fake_snapshot.fake_snapshot_obj(mock.MagicMock(), volume=srcvol)
        snap_name = snap["volume_name"] + "-cinder." + snap["name"]
        mock_get_replicated_type.return_value = None

        vol, vol_name = self.new_fake_vol(set_provider_id=False)
        mock_get_volume_type.return_value = vol.volume_type
        # Branch where extend unneeded
        self.driver.create_volume_from_snapshot(vol, snap)
        self.array.copy_volume.assert_called_with(snap_name, vol_name)
        self.assertFalse(self.array.extend_volume.called)
        mock_add_to_group.assert_called_once_with(vol, vol_name)
        self.assert_error_propagates(
            [self.array.copy_volume],
            self.driver.create_volume_from_snapshot, vol, snap)
        self.assertFalse(self.array.extend_volume.called)

    @mock.patch(BASE_DRIVER_OBJ + "._add_to_group_if_needed")
    @mock.patch(BASE_DRIVER_OBJ + "._get_replication_type_from_vol_type")
    @mock.patch.object(volume_types, 'get_volume_type')
    def test_create_volume_from_snapshot_with_extend(self,
                                                     mock_get_volume_type,
                                                     mock_get_replicated_type,
                                                     mock_add_to_group):
        srcvol, srcvol_name = self.new_fake_vol(spec={"size": 1})
        snap = fake_snapshot.fake_snapshot_obj(mock.MagicMock(), volume=srcvol)
        snap_name = snap["volume_name"] + "-cinder." + snap["name"]
        mock_get_replicated_type.return_value = None

        vol, vol_name = self.new_fake_vol(set_provider_id=False,
                                          spec={"size": 2})
        mock_get_volume_type.return_value = vol.volume_type

        self.driver.create_volume_from_snapshot(vol, snap)
        expected = [mock.call.copy_volume(snap_name, vol_name),
                    mock.call.extend_volume(vol_name, 2 * units.Gi)]
        self.array.assert_has_calls(expected)
        mock_add_to_group.assert_called_once_with(vol, vol_name)

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_create_volume_from_snapshot_sync(self, mock_get_volume_type):
        repl_extra_specs = {
            'replication_type': '<in> async',
            'replication_enabled': '<is> true',
        }
        srcvol, _ = self.new_fake_vol(type_extra_specs=repl_extra_specs)
        snap, snap_name = self.new_fake_snap(vol=srcvol)

        vol, vol_name = self.new_fake_vol(set_provider_id=False,
                                          type_extra_specs=repl_extra_specs)
        mock_get_volume_type.return_value = vol.volume_type
        self.driver.create_volume_from_snapshot(vol, snap)
        self.array.copy_volume.assert_called_with(snap_name, vol_name)

    @mock.patch(BASE_DRIVER_OBJ + "._add_to_group_if_needed")
    @mock.patch(BASE_DRIVER_OBJ + "._extend_if_needed", autospec=True)
    @mock.patch(BASE_DRIVER_OBJ + "._get_pgroup_snap_name_from_snapshot")
    @mock.patch(BASE_DRIVER_OBJ + "._get_replication_type_from_vol_type")
    @mock.patch.object(volume_types, 'get_volume_type')
    def test_create_volume_from_cgsnapshot(self, mock_get_volume_type,
                                           mock_get_replicated_type,
                                           mock_get_snap_name,
                                           mock_extend_if_needed,
                                           mock_add_to_group):
        cgroup = fake_group.fake_group_obj(mock.MagicMock())
        cgsnap = fake_group_snapshot.fake_group_snapshot_obj(mock.MagicMock(),
                                                             group=cgroup)
        vol, vol_name = self.new_fake_vol(spec={"group": cgroup})
        mock_get_volume_type.return_value = vol.volume_type
        snap = fake_snapshot.fake_snapshot_obj(mock.MagicMock(), volume=vol)
        snap.group_snapshot_id = cgsnap.id
        snap.group_snapshot = cgsnap
        snap_name = "consisgroup-%s-cinder.%s.%s-cinder" % (
            cgroup.id,
            snap.id,
            vol.name
        )
        mock_get_snap_name.return_value = snap_name
        mock_get_replicated_type.return_value = False

        self.driver.create_volume_from_snapshot(vol, snap)

        self.array.copy_volume.assert_called_with(snap_name, vol_name)
        self.assertTrue(mock_get_snap_name.called)
        self.assertTrue(mock_extend_if_needed.called)
        mock_add_to_group.assert_called_with(vol, vol_name)

    # Tests cloning a volume that is not replicated type
    @mock.patch(BASE_DRIVER_OBJ + "._add_to_group_if_needed")
    @mock.patch(BASE_DRIVER_OBJ + "._get_replication_type_from_vol_type")
    def test_create_cloned_volume(self, mock_get_replication_type,
                                  mock_add_to_group):
        vol, vol_name = self.new_fake_vol(set_provider_id=False)
        src_vol, src_name = self.new_fake_vol()
        mock_get_replication_type.return_value = None
        # Branch where extend unneeded
        self.driver.create_cloned_volume(vol, src_vol)
        self.array.copy_volume.assert_called_with(src_name, vol_name)
        self.assertFalse(self.array.extend_volume.called)
        mock_add_to_group.assert_called_once_with(vol,
                                                  vol_name)
        self.assert_error_propagates(
            [self.array.copy_volume],
            self.driver.create_cloned_volume, vol, src_vol)
        self.assertFalse(self.array.extend_volume.called)

    def test_create_cloned_volume_sync_rep(self):
        repl_extra_specs = {
            'replication_type': '<in> sync',
            'replication_enabled': '<is> true',
        }
        src_vol, src_name = self.new_fake_vol(
            type_extra_specs=repl_extra_specs)
        vol, vol_name = self.new_fake_vol(set_provider_id=False,
                                          type_extra_specs=repl_extra_specs)
        # Branch where extend unneeded
        self.driver.create_cloned_volume(vol, src_vol)
        self.array.copy_volume.assert_called_with(src_name, vol_name)
        self.assertFalse(self.array.extend_volume.called)

    @mock.patch(BASE_DRIVER_OBJ + "._add_to_group_if_needed")
    @mock.patch(BASE_DRIVER_OBJ + "._get_replication_type_from_vol_type")
    def test_create_cloned_volume_and_extend(self, mock_get_replication_type,
                                             mock_add_to_group):
        vol, vol_name = self.new_fake_vol(set_provider_id=False,
                                          spec={"size": 2})
        src_vol, src_name = self.new_fake_vol()
        mock_get_replication_type.return_value = None
        self.driver.create_cloned_volume(vol, src_vol)
        expected = [mock.call.copy_volume(src_name, vol_name),
                    mock.call.extend_volume(vol_name, 2 * units.Gi)]
        self.array.assert_has_calls(expected)
        mock_add_to_group.assert_called_once_with(vol,
                                                  vol_name)

    # Tests cloning a volume that is part of a consistency group
    @mock.patch(BASE_DRIVER_OBJ + "._add_to_group_if_needed")
    @mock.patch(BASE_DRIVER_OBJ + "._get_replication_type_from_vol_type")
    def test_create_cloned_volume_with_cgroup(self, mock_get_replication_type,
                                              mock_add_to_group):
        vol, vol_name = self.new_fake_vol(set_provider_id=False)
        group = fake_group.fake_group_obj(mock.MagicMock())
        src_vol, _ = self.new_fake_vol(spec={"group_id": group.id})
        mock_get_replication_type.return_value = None

        self.driver.create_cloned_volume(vol, src_vol)

        mock_add_to_group.assert_called_with(vol, vol_name)

    def test_delete_volume_already_deleted(self):
        self.array.list_volume_private_connections.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=400,
                text="Volume does not exist"
            )
        vol, _ = self.new_fake_vol()
        self.driver.delete_volume(vol)
        self.assertFalse(self.array.destroy_volume.called)
        self.assertFalse(self.array.eradicate_volume.called)

        # Testing case where array.destroy_volume returns an exception
        # because volume has already been deleted
        self.array.list_volume_private_connections.side_effect = None
        self.array.list_volume_private_connections.return_value = {}
        self.array.destroy_volume.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=http.client.BAD_REQUEST,
                text="Volume does not exist"
            )
        self.driver.delete_volume(vol)
        self.assertTrue(self.array.destroy_volume.called)
        self.assertFalse(self.array.eradicate_volume.called)

    def test_delete_volume(self):
        vol, vol_name = self.new_fake_vol()
        self.array.list_volume_private_connections.return_value = {}
        self.driver.delete_volume(vol)
        expected = [mock.call.destroy_volume(vol_name)]
        self.array.assert_has_calls(expected)
        self.assertFalse(self.array.eradicate_volume.called)
        self.array.destroy_volume.side_effect = (
            self.purestorage_module.PureHTTPError(code=http.client.BAD_REQUEST,
                                                  text="does not exist"))
        self.driver.delete_volume(vol)
        self.array.destroy_volume.side_effect = None
        self.assert_error_propagates([self.array.destroy_volume],
                                     self.driver.delete_volume, vol)

    def test_delete_volume_eradicate_now(self):
        vol, vol_name = self.new_fake_vol()
        self.array.list_volume_private_connections.return_value = {}
        self.mock_config.pure_eradicate_on_delete = True
        self.driver.delete_volume(vol)
        expected = [mock.call.destroy_volume(vol_name),
                    mock.call.eradicate_volume(vol_name)]
        self.array.assert_has_calls(expected)

    def test_delete_connected_volume(self):
        vol, vol_name = self.new_fake_vol()
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

        self.driver.delete_volume(vol)
        expected = [mock.call.list_volume_private_connections(vol_name,
                                                              remote=True),
                    mock.call.disconnect_host(host_name_a, vol_name),
                    mock.call.list_host_connections(host_name_a, private=True),
                    mock.call.disconnect_host(host_name_b, vol_name),
                    mock.call.list_host_connections(host_name_b, private=True),
                    mock.call.destroy_volume(vol_name)]
        self.array.assert_has_calls(expected)

    def test_delete_not_connected_pod_volume(self):
        type_spec = {
            'replication_type': '<in> sync',
            'replication_enabled': '<is> true',
        }
        vol, vol_name = self.new_fake_vol(type_extra_specs=type_spec)
        self.array.list_volume_private_connections.return_value = []
        # Set the array to be in a sync-rep enabled version
        self.array._list_available_rest_versions.return_value = [
            '1.0', '1.1', '1.2', '1.3', '1.4', '1.5', '1.6', '1.7', '1.8',
            '1.9', '1.10', '1.11', '1.12', '1.13', '1.14', '1.15', '1.16',
            '1.17', '1.18', '1.19']

        self.driver.delete_volume(vol)

        self.array.assert_has_calls([
            mock.call.list_volume_private_connections(vol_name, remote=True),
            mock.call.destroy_volume(vol_name),
        ])

    def test_delete_connected_pod_volume(self):
        type_spec = {
            'replication_type': '<in> sync',
            'replication_enabled': '<is> true',
        }
        vol, vol_name = self.new_fake_vol(type_extra_specs=type_spec)
        host_name_a = "ha"
        host_name_b = "hb"
        remote_host_a = "remote-fa1:ha"
        self.array.list_volume_private_connections.return_value = [
            {
                "host": host_name_a,
                "lun": 7,
                "name": vol_name,
                "size": 3221225472,
            },
            {
                "host": host_name_b,
                "lun": 2,
                "name": vol_name,
                "size": 3221225472,
            },
            {
                "host": remote_host_a,
                "lun": 1,
                "name": vol_name,
                "size": 3221225472,
            }
        ]

        # Set the array to be in a sync-rep enabled version
        self.array._list_available_rest_versions.return_value = [
            '1.0', '1.1', '1.2', '1.3', '1.4', '1.5', '1.6', '1.7', '1.8',
            '1.9', '1.10', '1.11', '1.12', '1.13', '1.14', '1.15', '1.16',
            '1.17', '1.18', '1.19']

        self.driver.delete_volume(vol)
        expected = [
            mock.call._list_available_rest_versions(),
            mock.call.list_volume_private_connections(vol_name, remote=True),
            mock.call.disconnect_host(host_name_a, vol_name),
            mock.call.list_host_connections(host_name_a, private=True),
            mock.call.disconnect_host(host_name_b, vol_name),
            mock.call.list_host_connections(host_name_b, private=True),
            mock.call.disconnect_host(remote_host_a, vol_name),
            mock.call.destroy_volume(vol_name)
        ]
        self.array.assert_has_calls(expected)

    def test_create_snapshot(self):
        vol, vol_name = self.new_fake_vol()
        snap = fake_snapshot.fake_snapshot_obj(mock.MagicMock(), volume=vol)
        self.driver.create_snapshot(snap)
        self.array.create_snapshot.assert_called_with(
            vol_name,
            suffix=snap["name"]
        )
        self.assert_error_propagates([self.array.create_snapshot],
                                     self.driver.create_snapshot, snap)

    @ddt.data("does not exist", "has been destroyed")
    def test_delete_snapshot(self, error_text):
        vol, _ = self.new_fake_vol()
        snap = fake_snapshot.fake_snapshot_obj(mock.MagicMock(), volume=vol)
        snap_name = snap["volume_name"] + "-cinder." + snap["name"]
        self.driver.delete_snapshot(snap)
        expected = [mock.call.destroy_volume(snap_name)]
        self.array.assert_has_calls(expected)
        self.assertFalse(self.array.eradicate_volume.called)
        self.array.destroy_volume.side_effect = (
            self.purestorage_module.PureHTTPError(code=http.client.BAD_REQUEST,
                                                  text=error_text))
        self.driver.delete_snapshot(snap)
        self.array.destroy_volume.side_effect = None
        self.assert_error_propagates([self.array.destroy_volume],
                                     self.driver.delete_snapshot, snap)

    def test_delete_snapshot_eradicate_now(self):
        vol, _ = self.new_fake_vol()
        snap = fake_snapshot.fake_snapshot_obj(mock.MagicMock(), volume=vol)
        snap_name = snap["volume_name"] + "-cinder." + snap["name"]
        self.mock_config.pure_eradicate_on_delete = True
        self.driver.delete_snapshot(snap)
        expected = [mock.call.destroy_volume(snap_name),
                    mock.call.eradicate_volume(snap_name)]
        self.array.assert_has_calls(expected)

    @mock.patch(BASE_DRIVER_OBJ + "._get_host", autospec=True)
    def test_terminate_connection(self, mock_host):
        vol, vol_name = self.new_fake_vol()
        mock_host.return_value = [{"name": "some-host"}]
        # Branch with manually created host
        self.driver.terminate_connection(vol, ISCSI_CONNECTOR)
        self.array.disconnect_host.assert_called_with("some-host", vol_name)
        self.assertTrue(self.array.list_host_connections.called)
        self.assertFalse(self.array.delete_host.called)
        # Branch with host added to host group
        self.array.reset_mock()
        self.array.list_host_connections.return_value = []
        mock_host.return_value = [PURE_HOST.copy()]
        mock_host.return_value[0].update(hgroup="some-group")
        self.driver.terminate_connection(vol, ISCSI_CONNECTOR)
        self.array.disconnect_host.assert_called_with(PURE_HOST_NAME, vol_name)
        self.assertTrue(self.array.list_host_connections.called)
        self.assertTrue(self.array.delete_host.called)
        # Branch with host still having connected volumes
        self.array.reset_mock()
        self.array.list_host_connections.return_value = [
            {"lun": 2, "name": PURE_HOST_NAME, "vol": "some-vol"}]
        mock_host.return_value = [PURE_HOST.copy()]
        self.driver.terminate_connection(vol, ISCSI_CONNECTOR)
        self.array.disconnect_host.assert_called_with(PURE_HOST_NAME, vol_name)
        self.array.list_host_connections.assert_called_with(PURE_HOST_NAME,
                                                            private=True)
        self.assertFalse(self.array.delete_host.called)
        # Branch where host gets deleted
        self.array.reset_mock()
        self.array.list_host_connections.return_value = []
        self.driver.terminate_connection(vol, ISCSI_CONNECTOR)
        self.array.disconnect_host.assert_called_with(PURE_HOST_NAME, vol_name)
        self.array.list_host_connections.assert_called_with(PURE_HOST_NAME,
                                                            private=True)
        self.array.delete_host.assert_called_with(PURE_HOST_NAME)
        # Branch where connection is missing and the host is still deleted
        self.array.reset_mock()
        self.array.disconnect_host.side_effect = \
            self.purestorage_module.PureHTTPError(code=http.client.BAD_REQUEST,
                                                  text="is not connected")
        self.driver.terminate_connection(vol, ISCSI_CONNECTOR)
        self.array.disconnect_host.assert_called_with(PURE_HOST_NAME, vol_name)
        self.array.list_host_connections.assert_called_with(PURE_HOST_NAME,
                                                            private=True)
        self.array.delete_host.assert_called_with(PURE_HOST_NAME)
        # Branch where an unexpected exception occurs
        self.array.reset_mock()
        self.array.disconnect_host.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=http.client.INTERNAL_SERVER_ERROR,
                text="Some other error"
            )
        self.assertRaises(self.purestorage_module.PureHTTPError,
                          self.driver.terminate_connection,
                          vol,
                          ISCSI_CONNECTOR)
        self.array.disconnect_host.assert_called_with(PURE_HOST_NAME, vol_name)
        self.assertFalse(self.array.list_host_connections.called)
        self.assertFalse(self.array.delete_host.called)

    @mock.patch(BASE_DRIVER_OBJ + "._disconnect_host")
    @mock.patch(BASE_DRIVER_OBJ + "._get_host", autospec=True)
    def test_terminate_connection_uniform_ac_remove_remote_hosts(
            self, mock_host, mock_disconnect):
        repl_extra_specs = {
            'replication_type': '<in> sync',
            'replication_enabled': '<is> true',
        }
        vol, vol_name = self.new_fake_vol(type_extra_specs=repl_extra_specs)
        self.driver._is_active_cluster_enabled = True
        mock_secondary = mock.MagicMock()
        self.driver._uniform_active_cluster_target_arrays = [mock_secondary]
        mock_host.side_effect = [
            [{"name": "some-host1"}],
            [{"name": "some-host2"}, {"name": "secondary-fa1:some-host1"}],
        ]

        self.driver.terminate_connection(vol, ISCSI_CONNECTOR)
        mock_disconnect.assert_has_calls([
            mock.call(mock_secondary, "some-host1", vol_name),
            mock.call(self.array, "some-host2", vol_name),
            mock.call(self.array, "secondary-fa1:some-host1", vol_name)
        ])

    @mock.patch(BASE_DRIVER_OBJ + "._disconnect_host")
    @mock.patch(BASE_DRIVER_OBJ + "._get_host", autospec=True)
    def test_terminate_connection_uniform_ac_no_remote_hosts(
            self, mock_host, mock_disconnect):
        repl_extra_specs = {
            'replication_type': '<in> sync',
            'replication_enabled': '<is> true',
        }
        vol, vol_name = self.new_fake_vol(type_extra_specs=repl_extra_specs)
        self.driver._is_active_cluster_enabled = True
        mock_secondary = mock.MagicMock()
        self.driver._uniform_active_cluster_target_arrays = [mock_secondary]
        mock_host.side_effect = [
            [],
            [{"name": "some-host2"}],
        ]

        self.driver.terminate_connection(vol, ISCSI_CONNECTOR)
        mock_disconnect.assert_has_calls([
            mock.call(self.array, "some-host2", vol_name),
        ])

    def _test_terminate_connection_with_error(self, mock_host, error):
        vol, vol_name = self.new_fake_vol()
        mock_host.return_value = [PURE_HOST.copy()]
        self.array.reset_mock()
        self.array.list_host_connections.return_value = []
        self.array.delete_host.side_effect = \
            self.purestorage_module.PureHTTPError(code=http.client.BAD_REQUEST,
                                                  text=error)
        self.driver.terminate_connection(vol, ISCSI_CONNECTOR)
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
        vol, vol_name = self.new_fake_vol()
        # Show the volume having a connection
        connections = [
            {"host": "h1", "name": vol_name},
            {"host": "h2", "name": vol_name},
        ]
        self.array.list_volume_private_connections.return_value = \
            [connections[0]]

        self.driver.terminate_connection(vol, None)
        self.array.disconnect_host.assert_called_with(
            connections[0]["host"],
            connections[0]["name"]
        )

    def test_terminate_connection_no_connector_no_host(self):
        vol, _ = self.new_fake_vol()

        # Show the volume not having a connection
        self.array.list_volume_private_connections.return_value = []

        self.driver.terminate_connection(vol, None)
        self.array.disconnect_host.assert_not_called()

    def test_extend_volume(self):
        vol, vol_name = self.new_fake_vol(spec={"size": 1})
        self.driver.extend_volume(vol, 3)
        self.array.extend_volume.assert_called_with(vol_name, 3 * units.Gi)
        self.assert_error_propagates([self.array.extend_volume],
                                     self.driver.extend_volume, vol, 3)

    @ddt.data(
        dict(
            repl_types=[None],
            id=fake.GROUP_ID,
            expected_name=("consisgroup-%s-cinder" % fake.GROUP_ID)
        ),
        dict(
            repl_types=['async'],
            id=fake.GROUP_ID,
            expected_name=("consisgroup-%s-cinder" % fake.GROUP_ID)
        ),
        dict(
            repl_types=[None, 'async'],
            id=fake.GROUP_ID,
            expected_name=("consisgroup-%s-cinder" % fake.GROUP_ID)
        ),
        dict(
            repl_types=['sync'],
            id=fake.GROUP_ID,
            expected_name=("cinder-pod::consisgroup-%s-cinder" % fake.GROUP_ID)
        ),
        dict(
            repl_types=[None, 'sync'],
            id=fake.GROUP_ID,
            expected_name=("cinder-pod::consisgroup-%s-cinder" % fake.GROUP_ID)
        ),
        dict(
            repl_types=['sync', 'async'],
            id=fake.GROUP_ID,
            expected_name=("cinder-pod::consisgroup-%s-cinder" % fake.GROUP_ID)
        ),
        dict(
            repl_types=[None, 'sync', 'async'],
            id=fake.GROUP_ID,
            expected_name=("cinder-pod::consisgroup-%s-cinder" % fake.GROUP_ID)
        ),
    )
    @ddt.unpack
    def test_get_pgroup_name(self, repl_types, id, expected_name):
        pgroup = fake_group.fake_group_obj(mock.MagicMock(), id=id)
        vol_types = []
        for repl_type in repl_types:
            vol_type = fake_volume.fake_volume_type_obj(None)
            if repl_type is not None:
                repl_extra_specs = {
                    'replication_type': '<in> %s' % repl_type,
                    'replication_enabled': '<is> true',
                }
                vol_type.extra_specs = repl_extra_specs
            vol_types.append(vol_type)
        pgroup.volume_types = volume_type.VolumeTypeList(objects=vol_types)
        actual_name = self.driver._get_pgroup_name(pgroup)
        self.assertEqual(expected_name, actual_name)

    def test_get_pgroup_snap_suffix(self):
        cgsnap = {
            'id': "4a2f7e3a-312a-40c5-96a8-536b8a0fe074"
        }
        expected_suffix = "cgsnapshot-%s-cinder" % cgsnap['id']
        actual_suffix = self.driver._get_pgroup_snap_suffix(cgsnap)
        self.assertEqual(expected_suffix, actual_suffix)

    @mock.patch(BASE_DRIVER_OBJ + "._get_pgroup_name")
    def test_get_pgroup_snap_name(self, mock_get_pgroup_name):
        cg = fake_group.fake_group_obj(mock.MagicMock())
        cgsnap = fake_group_snapshot.fake_group_snapshot_obj(mock.MagicMock())
        cgsnap.group_id = cg.id
        cgsnap.group = cg
        group_name = "consisgroup-%s-cinder" % cg.id
        mock_get_pgroup_name.return_value = group_name
        expected_name = ("%(group_name)s.cgsnapshot-%(snap)s-cinder" % {
            "group_name": group_name, "snap": cgsnap.id})

        actual_name = self.driver._get_pgroup_snap_name(cgsnap)

        self.assertEqual(expected_name, actual_name)

    def test_get_pgroup_snap_name_from_snapshot(self):
        vol, _ = self.new_fake_vol()
        cg = fake_group.fake_group_obj(mock.MagicMock())
        cgsnap = fake_group_snapshot.fake_group_snapshot_obj(mock.MagicMock())
        cgsnap.group_id = cg.id
        cgsnap.group = cg

        pgsnap_name_base = (
            'consisgroup-%s-cinder.cgsnapshot-%s-cinder.%s-cinder')
        pgsnap_name = pgsnap_name_base % (cg.id, cgsnap.id, vol.name)

        snap, _ = self.new_fake_snap(vol=vol, group_snap=cgsnap)

        actual_name = self.driver._get_pgroup_snap_name_from_snapshot(
            snap
        )
        self.assertEqual(pgsnap_name, actual_name)

    @mock.patch(BASE_DRIVER_OBJ + "._group_potential_repl_types")
    def test_create_consistencygroup(self, mock_get_repl_types):
        cgroup = fake_group.fake_group_obj(mock.MagicMock())
        mock_get_repl_types.return_value = set()

        model_update = self.driver.create_consistencygroup(None, cgroup)

        expected_name = "consisgroup-" + cgroup.id + "-cinder"
        self.array.create_pgroup.assert_called_with(expected_name)
        self.assertEqual({'status': 'available'}, model_update)

        self.assert_error_propagates(
            [self.array.create_pgroup],
            self.driver.create_consistencygroup, None, cgroup)

    @mock.patch(BASE_DRIVER_OBJ + "._group_potential_repl_types")
    def test_create_consistencygroup_in_pod(self, mock_get_repl_types):
        cgroup = fake_group.fake_group_obj(mock.MagicMock())
        mock_get_repl_types.return_value = ['sync', 'async']

        model_update = self.driver.create_consistencygroup(None, cgroup)

        expected_name = "cinder-pod::consisgroup-" + cgroup.id + "-cinder"
        self.array.create_pgroup.assert_called_with(expected_name)
        self.assertEqual({'status': 'available'}, model_update)

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
        self.assertTrue(self.array.destroy_pgroup.called)

    @mock.patch(BASE_DRIVER_OBJ + ".delete_volume", autospec=True)
    def test_delete_consistencygroup(self, mock_delete_volume):
        mock_context = mock.Mock()
        mock_cgroup = fake_group.fake_group_obj(mock_context)
        mock_volume = fake_volume.fake_volume_obj(mock_context)

        model_update, volumes = self.driver.delete_consistencygroup(
            mock_context, mock_cgroup, [mock_volume])

        expected_name = "consisgroup-%s-cinder" % mock_cgroup.id
        self.array.destroy_pgroup.assert_called_with(expected_name)
        self.assertFalse(self.array.eradicate_pgroup.called)
        self.assertIsNone(volumes)
        self.assertIsNone(model_update)
        mock_delete_volume.assert_called_with(self.driver, mock_volume)

        self.array.destroy_pgroup.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=http.client.BAD_REQUEST,
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
                code=http.client.BAD_REQUEST,
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
                code=http.client.BAD_REQUEST,
                text="Some other error"
            )
        self.assertRaises(self.purestorage_module.PureHTTPError,
                          self.driver.delete_consistencygroup,
                          mock_context,
                          mock_cgroup,
                          [mock_volume])

        self.array.destroy_pgroup.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=http.client.INTERNAL_SERVER_ERROR,
                text="Another different error"
            )
        self.assertRaises(self.purestorage_module.PureHTTPError,
                          self.driver.delete_consistencygroup,
                          mock_context,
                          mock_cgroup,
                          [mock_volume])

        self.array.destroy_pgroup.side_effect = None
        self.assert_error_propagates(
            [self.array.destroy_pgroup],
            self.driver.delete_consistencygroup,
            mock_context,
            mock_cgroup,
            [mock_volume]
        )

    def test_update_consistencygroup(self):
        group, group_name = self.new_fake_group()
        add_vols = [
            self.new_fake_vol(spec={"id": fake.VOLUME_ID}),
            self.new_fake_vol(spec={"id": fake.VOLUME2_ID}),
            self.new_fake_vol(spec={"id": fake.VOLUME3_ID}),
        ]
        add_vol_objs = []
        expected_addvollist = []
        for vol in add_vols:
            add_vol_objs.append(vol[0])
            expected_addvollist.append(vol[1])

        remove_vols = [
            self.new_fake_vol(spec={"id": fake.VOLUME4_ID}),
            self.new_fake_vol(spec={"id": fake.VOLUME5_ID}),
        ]
        rem_vol_objs = []
        expected_remvollist = []
        for vol in remove_vols:
            rem_vol_objs.append(vol[0])
            expected_remvollist.append(vol[1])

        self.driver.update_consistencygroup(mock.Mock(), group,
                                            add_vol_objs, rem_vol_objs)
        self.array.set_pgroup.assert_called_with(
            group_name,
            addvollist=expected_addvollist,
            remvollist=expected_remvollist
        )

    def test_update_consistencygroup_no_add_vols(self):
        group, group_name = self.new_fake_group()
        expected_addvollist = []
        remove_vols = [
            self.new_fake_vol(spec={"id": fake.VOLUME4_ID}),
            self.new_fake_vol(spec={"id": fake.VOLUME5_ID}),
        ]
        rem_vol_objs = []
        expected_remvollist = []
        for vol in remove_vols:
            rem_vol_objs.append(vol[0])
            expected_remvollist.append(vol[1])
        self.driver.update_consistencygroup(mock.Mock(), group,
                                            None, rem_vol_objs)
        self.array.set_pgroup.assert_called_with(
            group_name,
            addvollist=expected_addvollist,
            remvollist=expected_remvollist
        )

    def test_update_consistencygroup_no_remove_vols(self):
        group, group_name = self.new_fake_group()
        add_vols = [
            self.new_fake_vol(spec={"id": fake.VOLUME_ID}),
            self.new_fake_vol(spec={"id": fake.VOLUME2_ID}),
            self.new_fake_vol(spec={"id": fake.VOLUME3_ID}),
        ]
        add_vol_objs = []
        expected_addvollist = []
        for vol in add_vols:
            add_vol_objs.append(vol[0])
            expected_addvollist.append(vol[1])
        expected_remvollist = []
        self.driver.update_consistencygroup(mock.Mock(), group,
                                            add_vol_objs, None)
        self.array.set_pgroup.assert_called_with(
            group_name,
            addvollist=expected_addvollist,
            remvollist=expected_remvollist
        )

    def test_update_consistencygroup_no_vols(self):
        group, group_name = self.new_fake_group()
        self.driver.update_consistencygroup(mock.Mock(), group,
                                            None, None)
        self.array.set_pgroup.assert_called_with(
            group_name,
            addvollist=[],
            remvollist=[]
        )

    def test_create_cgsnapshot(self):
        mock_context = mock.Mock()
        mock_group = fake_group.fake_group_obj(mock_context)
        mock_cgsnap = fake_group_snapshot.fake_group_snapshot_obj(
            mock_context, group_id=mock_group.id)
        mock_snap = fake_snapshot.fake_snapshot_obj(mock_context)

        # Avoid having the group snapshot object load from the db
        with mock.patch('cinder.objects.Group.get_by_id') as mock_get_group:
            mock_get_group.return_value = mock_group

            model_update, snapshots = self.driver.create_cgsnapshot(
                mock_context, mock_cgsnap, [mock_snap])

        expected_pgroup_name = self.driver._get_pgroup_name(mock_group)
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
                code=http.client.BAD_REQUEST,
                text="Protection group snapshot has been destroyed."
            )
        self.driver.delete_cgsnapshot(mock_context, mock_cgsnap, [mock_snap])
        self.array.destroy_pgroup.assert_called_with(snap_name)
        self.assertFalse(self.array.eradicate_pgroup.called)

        self.array.destroy_pgroup.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=http.client.BAD_REQUEST,
                text="Protection group snapshot does not exist"
            )
        self.driver.delete_cgsnapshot(mock_context, mock_cgsnap, [mock_snap])
        self.array.destroy_pgroup.assert_called_with(snap_name)
        self.assertFalse(self.array.eradicate_pgroup.called)

        self.array.destroy_pgroup.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=http.client.BAD_REQUEST,
                text="Some other error"
            )
        self.assertRaises(self.purestorage_module.PureHTTPError,
                          self.driver.delete_cgsnapshot,
                          mock_context,
                          mock_cgsnap,
                          [mock_snap])

        self.array.destroy_pgroup.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=http.client.INTERNAL_SERVER_ERROR,
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
        vol, vol_name = self.new_fake_vol(set_provider_id=False)
        self.driver.manage_existing(vol, volume_ref)
        self.array.list_volume_private_connections.assert_called_with(ref_name)
        self.array.rename_volume.assert_called_with(ref_name, vol_name)

    def test_manage_existing_error_propagates(self):
        self.array.list_volume_private_connections.return_value = []
        vol, _ = self.new_fake_vol(set_provider_id=False)
        self.assert_error_propagates(
            [self.array.list_volume_private_connections,
             self.array.rename_volume],
            self.driver.manage_existing,
            vol, {'name': 'vol1'}
        )

    def test_manage_existing_bad_ref(self):
        vol, _ = self.new_fake_vol(set_provider_id=False)
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing,
                          vol, {'bad_key': 'bad_value'})

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing,
                          vol, {'name': ''})

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing,
                          vol, {'name': None})

        self.array.get_volume.side_effect = \
            self.purestorage_module.PureHTTPError(
                text="Volume does not exist.",
                code=http.client.BAD_REQUEST
            )
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing,
                          vol, {'name': 'non-existing-volume'})

    def test_manage_existing_sync_repl_type(self):
        ref_name = 'vol1'
        volume_ref = {'name': ref_name}
        type_spec = {
            'replication_type': '<in> sync',
            'replication_enabled': '<is> true',
        }
        self.array.list_volume_private_connections.return_value = []
        vol, vol_name = self.new_fake_vol(set_provider_id=False,
                                          type_extra_specs=type_spec)

        self.assertRaises(exception.ManageExistingVolumeTypeMismatch,
                          self.driver.manage_existing,
                          vol, volume_ref)

    def test_manage_existing_vol_in_pod(self):
        ref_name = 'somepod::vol1'
        volume_ref = {'name': ref_name}
        self.array.list_volume_private_connections.return_value = []
        vol, vol_name = self.new_fake_vol(set_provider_id=False)

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing,
                          vol, volume_ref)

    def test_manage_existing_with_connected_hosts(self):
        ref_name = 'vol1'
        self.array.list_volume_private_connections.return_value = \
            ["host1", "host2"]
        vol, _ = self.new_fake_vol(set_provider_id=False)
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing,
                          vol, {'name': ref_name})

        self.array.list_volume_private_connections.assert_called_with(ref_name)
        self.assertFalse(self.array.rename_volume.called)

    def test_manage_existing_get_size(self):
        ref_name = 'vol1'
        volume_ref = {'name': ref_name}
        expected_size = 5
        self.array.get_volume.return_value = {"size": 5368709120}
        vol, _ = self.new_fake_vol(set_provider_id=False)

        size = self.driver.manage_existing_get_size(vol, volume_ref)

        self.assertEqual(expected_size, size)
        self.array.get_volume.assert_called_with(ref_name, snap=False)

    def test_manage_existing_get_size_error_propagates(self):
        self.array.get_volume.return_value = mock.MagicMock()
        vol, _ = self.new_fake_vol(set_provider_id=False)
        self.assert_error_propagates([self.array.get_volume],
                                     self.driver.manage_existing_get_size,
                                     vol, {'name': 'vol1'})

    def test_manage_existing_get_size_bad_ref(self):
        vol, _ = self.new_fake_vol(set_provider_id=False)
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size,
                          vol, {'bad_key': 'bad_value'})

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size,
                          vol, {'name': ''})

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size,
                          vol, {'name': None})

    def test_unmanage(self):
        vol, vol_name = self.new_fake_vol()
        unmanaged_vol_name = vol_name + UNMANAGED_SUFFIX

        self.driver.unmanage(vol)

        self.array.rename_volume.assert_called_with(vol_name,
                                                    unmanaged_vol_name)

    def test_unmanage_error_propagates(self):
        vol, _ = self.new_fake_vol()
        self.assert_error_propagates([self.array.rename_volume],
                                     self.driver.unmanage,
                                     vol)

    def test_unmanage_with_deleted_volume(self):
        vol, vol_name = self.new_fake_vol()
        unmanaged_vol_name = vol_name + UNMANAGED_SUFFIX
        self.array.rename_volume.side_effect = \
            self.purestorage_module.PureHTTPError(
                text="Volume does not exist.",
                code=http.client.BAD_REQUEST
            )

        self.driver.unmanage(vol)

        self.array.rename_volume.assert_called_with(vol_name,
                                                    unmanaged_vol_name)

    def test_manage_existing_snapshot(self):
        ref_name = PURE_SNAPSHOT['name']
        snap_ref = {'name': ref_name}
        snap, snap_name = self.new_fake_snap()
        self.array.get_volume.return_value = [PURE_SNAPSHOT]
        self.driver.manage_existing_snapshot(snap, snap_ref)
        self.array.rename_volume.assert_called_once_with(ref_name,
                                                         snap_name)
        self.array.get_volume.assert_called_with(PURE_SNAPSHOT['source'],
                                                 snap=True)

    def test_manage_existing_snapshot_multiple_snaps_on_volume(self):
        ref_name = PURE_SNAPSHOT['name']
        snap_ref = {'name': ref_name}
        pure_snaps = [PURE_SNAPSHOT]
        snap, snap_name = self.new_fake_snap()
        for i in range(5):
            pure_snap = PURE_SNAPSHOT.copy()
            pure_snap['name'] += str(i)
            pure_snaps.append(pure_snap)
        self.array.get_volume.return_value = pure_snaps
        self.driver.manage_existing_snapshot(snap, snap_ref)
        self.array.rename_volume.assert_called_once_with(ref_name,
                                                         snap_name)

    def test_manage_existing_snapshot_error_propagates(self):
        self.array.get_volume.return_value = [PURE_SNAPSHOT]
        snap, _ = self.new_fake_snap()
        self.assert_error_propagates(
            [self.array.rename_volume],
            self.driver.manage_existing_snapshot,
            snap, {'name': PURE_SNAPSHOT['name']}
        )

    def test_manage_existing_snapshot_bad_ref(self):
        snap, _ = self.new_fake_snap()
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot,
                          snap, {'bad_key': 'bad_value'})

    def test_manage_existing_snapshot_empty_ref(self):
        snap, _ = self.new_fake_snap()
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot,
                          snap, {'name': ''})

    def test_manage_existing_snapshot_none_ref(self):
        snap, _ = self.new_fake_snap()
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot,
                          snap, {'name': None})

    def test_manage_existing_snapshot_volume_ref_not_exist(self):
        snap, _ = self.new_fake_snap()
        self.array.get_volume.side_effect = \
            self.purestorage_module.PureHTTPError(
                text="Volume does not exist.",
                code=http.client.BAD_REQUEST
            )
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot,
                          snap, {'name': 'non-existing-volume.snap1'})

    def test_manage_existing_snapshot_ref_not_exist(self):
        ref_name = PURE_SNAPSHOT['name'] + '-fake'
        snap_ref = {'name': ref_name}
        snap, _ = self.new_fake_snap()
        self.array.get_volume.return_value = [PURE_SNAPSHOT]
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot,
                          snap, snap_ref)

    def test_manage_existing_snapshot_bad_api_version(self):
        self.array._list_available_rest_versions.return_value = ['1.0', '1.1',
                                                                 '1.2']
        snap, _ = self.new_fake_snap()
        self.assertRaises(pure.PureDriverException,
                          self.driver.manage_existing_snapshot,
                          snap, {'name': PURE_SNAPSHOT['name']})

    def test_manage_existing_snapshot_get_size(self):
        ref_name = PURE_SNAPSHOT['name']
        snap_ref = {'name': ref_name}
        self.array.get_volume.return_value = [PURE_SNAPSHOT]
        snap, _ = self.new_fake_snap()

        size = self.driver.manage_existing_snapshot_get_size(snap,
                                                             snap_ref)
        expected_size = 3.0
        self.assertEqual(expected_size, size)
        self.array.get_volume.assert_called_with(PURE_SNAPSHOT['source'],
                                                 snap=True)

    def test_manage_existing_snapshot_get_size_error_propagates(self):
        self.array.get_volume.return_value = [PURE_SNAPSHOT]
        snap, _ = self.new_fake_snap()
        self.assert_error_propagates(
            [self.array.get_volume],
            self.driver.manage_existing_snapshot_get_size,
            snap, {'name': PURE_SNAPSHOT['name']}
        )

    def test_manage_existing_snapshot_get_size_bad_ref(self):
        snap, _ = self.new_fake_snap()
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot_get_size,
                          snap, {'bad_key': 'bad_value'})

    def test_manage_existing_snapshot_get_size_empty_ref(self):
        snap, _ = self.new_fake_snap()
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot_get_size,
                          snap, {'name': ''})

    def test_manage_existing_snapshot_get_size_none_ref(self):
        snap, _ = self.new_fake_snap()
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot_get_size,
                          snap, {'name': None})

    def test_manage_existing_snapshot_get_size_volume_ref_not_exist(self):
        snap, _ = self.new_fake_snap()
        self.array.get_volume.side_effect = \
            self.purestorage_module.PureHTTPError(
                text="Volume does not exist.",
                code=http.client.BAD_REQUEST
            )
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot_get_size,
                          snap, {'name': 'non-existing-volume.snap1'})

    def test_manage_existing_snapshot_get_size_bad_api_version(self):
        snap, _ = self.new_fake_snap()
        self.array._list_available_rest_versions.return_value = ['1.0', '1.1',
                                                                 '1.2']
        self.assertRaises(pure.PureDriverException,
                          self.driver.manage_existing_snapshot_get_size,
                          snap, {'name': PURE_SNAPSHOT['name']})

    @ddt.data(
        # 96 chars, will exceed allowable length
        'volume-1e5177e7-95e5-4a0f-b170-e45f4b469f6a-cinder.'
        'snapshot-253b2878-ec60-4793-ad19-e65496ec7aab',
        # short_name that will require no adjustment
        'volume-1e5177e7-cinder.snapshot-e65496ec7aab')
    @mock.patch(BASE_DRIVER_OBJ + "._get_snap_name")
    def test_unmanage_snapshot(self, fake_name, mock_get_snap_name):
        snap, _ = self.new_fake_snap()
        mock_get_snap_name.return_value = fake_name
        self.driver.unmanage_snapshot(snap)
        self.array.rename_volume.assert_called_once()
        old_name = self.array.rename_volume.call_args[0][0]
        new_name = self.array.rename_volume.call_args[0][1]
        self.assertEqual(fake_name, old_name)
        self.assertLessEqual(len(new_name), MAX_SNAP_LENGTH)
        self.assertTrue(new_name.endswith(UNMANAGED_SUFFIX))

    def test_unmanage_snapshot_error_propagates(self):
        snap, _ = self.new_fake_snap()
        self.assert_error_propagates([self.array.rename_volume],
                                     self.driver.unmanage_snapshot,
                                     snap)

    def test_unmanage_snapshot_with_deleted_snapshot(self):
        snap, snap_name = self.new_fake_snap()
        if len(snap_name + UNMANAGED_SUFFIX) > MAX_SNAP_LENGTH:
            unmanaged_snap_name = snap_name[:-len(UNMANAGED_SUFFIX)] + \
                UNMANAGED_SUFFIX
        else:
            unmanaged_snap_name = snap_name
        self.array.rename_volume.side_effect = \
            self.purestorage_module.PureHTTPError(
                text="Snapshot does not exist.",
                code=http.client.BAD_REQUEST
            )

        self.driver.unmanage_snapshot(snap)

        self.array.rename_volume.assert_called_with(snap_name,
                                                    unmanaged_snap_name)

    def test_unmanage_snapshot_bad_api_version(self):
        snap, _ = self.new_fake_snap()
        self.array._list_available_rest_versions.return_value = ['1.0', '1.1',
                                                                 '1.2']
        self.assertRaises(pure.PureDriverException,
                          self.driver.unmanage_snapshot,
                          snap)

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

        with mock.patch('cinder.volume.volume_utils.'
                        'paginate_entries_list') as mpage:
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
        expected_refs[0]['reason_not_safe'] = 'Volume connected to host host2'

        self._test_get_manageable_things(expected_refs=expected_refs,
                                         pure_hosts=pure_hosts)

    def test_get_manageable_volumes_already_managed(self):
        """Make sure volumes already owned by cinder are flagged as unsafe."""
        cinder_vol, cinder_vol_name = self.new_fake_vol()
        cinders_vols = [cinder_vol]

        # Have one of our vol names match up with the existing cinder volume
        purity_vols = deepcopy(MANAGEABLE_PURE_VOLS)
        purity_vols[0]['name'] = cinder_vol_name

        expected_refs = deepcopy(MANAGEABLE_PURE_VOL_REFS)
        expected_refs[0]['reference'] = {'name': purity_vols[0]['name']}
        expected_refs[0]['safe_to_manage'] = False
        expected_refs[0]['reason_not_safe'] = 'Volume already managed'
        expected_refs[0]['cinder_id'] = cinder_vol.id

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
        cinder_vol, _ = self.new_fake_vol()
        cinder_snap = fake_snapshot.fake_snapshot_obj(mock.MagicMock())
        cinder_snap.volume = cinder_vol
        cinder_snaps = [cinder_snap]

        purity_snaps = deepcopy(MANAGEABLE_PURE_SNAPS)
        purity_snaps[0]['name'] = 'volume-%s-cinder.snapshot-%s' % (
            cinder_vol.id, cinder_snap.id
        )

        expected_refs = deepcopy(MANAGEABLE_PURE_SNAP_REFS)
        expected_refs[0]['reference'] = {'name': purity_snaps[0]['name']}
        expected_refs[0]['safe_to_manage'] = False
        expected_refs[0]['reason_not_safe'] = 'Snapshot already managed.'
        expected_refs[0]['cinder_id'] = cinder_snap.id

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

    @ddt.data(
        # No replication change, non-replicated
        dict(
            current_spec={
                'replication_enabled': '<is> false',
            },
            new_spec={
                'replication_type': '<in> async',
                'replication_enabled': '<is> false',
            },
            expected_model_update=None,
            expected_did_retype=True,
            expected_add_to_group=False,
            expected_remove_from_pgroup=False,
        ),
        # No replication change, async to async
        dict(
            current_spec={
                'replication_type': '<in> async',
                'replication_enabled': '<is> true',
                'other_spec': 'blah'
            },
            new_spec={
                'replication_type': '<in> async',
                'replication_enabled': '<is> true',
                'other_spec': 'something new'
            },
            expected_model_update=None,
            expected_did_retype=True,
            expected_add_to_group=False,
            expected_remove_from_pgroup=False,
        ),
        # No replication change, sync to sync
        dict(
            current_spec={
                'replication_type': '<in> sync',
                'replication_enabled': '<is> true',
                'other_spec': 'blah'
            },
            new_spec={
                'replication_type': '<in> sync',
                'replication_enabled': '<is> true',
                'other_spec': 'something new'
            },
            expected_model_update=None,
            expected_did_retype=True,
            expected_add_to_group=False,
            expected_remove_from_pgroup=False,
        ),
        # Turn on async rep
        dict(
            current_spec={
                'replication_enabled': '<is> false',
            },
            new_spec={
                'replication_type': '<in> async',
                'replication_enabled': '<is> true',
            },
            expected_model_update={
                "replication_status": fields.ReplicationStatus.ENABLED
            },
            expected_did_retype=True,
            expected_add_to_group=True,
            expected_remove_from_pgroup=False,
        ),
        # Turn off async rep
        dict(
            current_spec={
                'replication_type': '<in> async',
                'replication_enabled': '<is> true',
            },
            new_spec={
                'replication_type': '<in> async',
                'replication_enabled': '<is> false',
            },

            expected_model_update={
                "replication_status": fields.ReplicationStatus.DISABLED
            },
            expected_did_retype=True,
            expected_add_to_group=False,
            expected_remove_from_pgroup=True,
        ),
        # Turn on sync rep
        dict(
            current_spec={
                'replication_enabled': '<is> false',
            },
            new_spec={
                'replication_type': '<in> sync',
                'replication_enabled': '<is> true',
            },
            expected_model_update=None,
            # cannot retype via fast path to/from sync rep
            expected_did_retype=False,
            expected_add_to_group=False,
            expected_remove_from_pgroup=False,
        ),
        # Turn off sync rep
        dict(
            current_spec={
                'replication_type': '<in> sync',
                'replication_enabled': '<is> true',
            },
            new_spec={
                'replication_type': '<in> sync',
                'replication_enabled': '<is> false',
            },
            expected_model_update=None,
            # cannot retype via fast path to/from sync rep
            expected_did_retype=False,
            expected_add_to_group=False,
            expected_remove_from_pgroup=False,
        ),
        # Change from async to sync rep
        dict(
            current_spec={
                'replication_type': '<in> async',
                'replication_enabled': '<is> true',
            },
            new_spec={
                'replication_type': '<in> sync',
                'replication_enabled': '<is> true',
            },
            expected_model_update=None,
            # cannot retype via fast path to/from sync rep
            expected_did_retype=False,
            expected_add_to_group=False,
            expected_remove_from_pgroup=False,
        ),
        # Change from sync to async rep
        dict(
            current_spec={
                'replication_type': '<in> sync',
                'replication_enabled': '<is> true',
            },
            new_spec={
                'replication_type': '<in> async',
                'replication_enabled': '<is> true',
            },
            expected_model_update=None,
            # cannot retype via fast path to/from sync rep
            expected_did_retype=False,
            expected_add_to_group=False,
            expected_remove_from_pgroup=False,
        ),
    )
    @ddt.unpack
    def test_retype_replication(self,
                                current_spec,
                                new_spec,
                                expected_model_update,
                                expected_did_retype,
                                expected_add_to_group,
                                expected_remove_from_pgroup):
        mock_context = mock.MagicMock()
        vol, vol_name = self.new_fake_vol(type_extra_specs=current_spec)
        new_type = fake_volume.fake_volume_type_obj(mock_context)
        new_type.extra_specs = new_spec
        get_voltype = "cinder.objects.volume_type.VolumeType.get_by_name_or_id"
        with mock.patch(get_voltype) as mock_get_vol_type:
            mock_get_vol_type.return_value = new_type
            did_retype, model_update = self.driver.retype(
                mock_context,
                vol,
                {"id": new_type.id, "extra_specs": new_spec},
                None,  # ignored by driver
                None,  # ignored by driver
            )

        self.assertEqual(expected_did_retype, did_retype)
        self.assertEqual(expected_model_update, model_update)
        if expected_add_to_group:
            self.array.set_pgroup.assert_called_once_with(
                self.driver._replication_pg_name,
                addvollist=[vol_name]
            )
        if expected_remove_from_pgroup:
            self.array.set_pgroup.assert_called_once_with(
                self.driver._replication_pg_name,
                remvollist=[vol_name]
            )

    @ddt.data(
        dict(
            specs={
                'replication_type': '<in> async',
                'replication_enabled': '<is> true',
            },
            expected_repl_type='async'
        ),
        dict(
            specs={
                'replication_type': '<in> sync',
                'replication_enabled': '<is> true',
            },
            expected_repl_type='sync'
        ),
        dict(
            specs={
                'replication_type': '<in> async',
                'replication_enabled': '<is> false',
            },
            expected_repl_type=None
        ),
        dict(
            specs={
                'replication_type': '<in> sync',
                'replication_enabled': '<is> false',
            },
            expected_repl_type=None
        ),
        dict(
            specs={
                'not_replication_stuff': 'foo',
                'replication_enabled': '<is> true',
            },
            expected_repl_type='async'
        ),
        dict(
            specs=None,
            expected_repl_type=None
        ),
        dict(
            specs={
                'replication_type': '<in> super-turbo-repl-mode',
                'replication_enabled': '<is> true',
            },
            expected_repl_type=None
        )
    )
    @ddt.unpack
    def test_get_replication_type_from_vol_type(self, specs,
                                                expected_repl_type):
        voltype = fake_volume.fake_volume_type_obj(mock.MagicMock())
        voltype.extra_specs = specs
        actual_type = self.driver._get_replication_type_from_vol_type(voltype)
        self.assertEqual(expected_repl_type, actual_type)

    def test_does_pgroup_exist_not_exists(self):
        self.array.get_pgroup.side_effect = (
            self.purestorage_module.PureHTTPError(code=http.client.BAD_REQUEST,
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
            pure.PureDriverException,
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
            pure.PureDriverException,
            self.driver._wait_until_source_array_allowed,
            self.array,
            "some_pgroup",
        )

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_create_volume_replicated_async(self, mock_get_volume_type):
        repl_extra_specs = {
            'replication_type': '<in> async',
            'replication_enabled': '<is> true',
        }
        vol, vol_name = self.new_fake_vol(spec={"size": 2},
                                          type_extra_specs=repl_extra_specs)
        mock_get_volume_type.return_value = vol.volume_type

        self.driver.create_volume(vol)

        self.array.create_volume.assert_called_with(
            vol["name"] + "-cinder", 2 * units.Gi)
        self.array.set_pgroup.assert_called_with(
            REPLICATION_PROTECTION_GROUP,
            addvollist=[vol["name"] + "-cinder"])

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_create_volume_replicated_sync(self, mock_get_volume_type):
        repl_extra_specs = {
            'replication_type': '<in> sync',
            'replication_enabled': '<is> true',
        }
        vol, vol_name = self.new_fake_vol(spec={"size": 2},
                                          type_extra_specs=repl_extra_specs)

        mock_get_volume_type.return_value = vol.volume_type

        self.driver.create_volume(vol)

        self.array.create_volume.assert_called_with(
            "cinder-pod::" + vol["name"] + "-cinder", 2 * units.Gi)

    def test_find_async_failover_target_no_repl_targets(self):
        self.driver._replication_target_arrays = []
        self.assertRaises(pure.PureDriverException,
                          self.driver._find_async_failover_target)

    @mock.patch(BASE_DRIVER_OBJ + '._get_latest_replicated_pg_snap')
    def test_find_async_failover_target(self, mock_get_snap):
        mock_backend_1 = mock.Mock()
        mock_backend_1.replication_type = 'async'
        mock_backend_2 = mock.Mock()
        mock_backend_2.replication_type = 'async'
        self.driver._replication_target_arrays = [mock_backend_1,
                                                  mock_backend_2]
        mock_get_snap.return_value = REPLICATED_PGSNAPS[0]

        array, pg_snap = self.driver._find_async_failover_target()
        self.assertEqual(mock_backend_1, array)
        self.assertEqual(REPLICATED_PGSNAPS[0], pg_snap)

    @mock.patch(BASE_DRIVER_OBJ + '._get_latest_replicated_pg_snap')
    def test_find_async_failover_target_missing_pgsnap(
            self, mock_get_snap):
        mock_backend_1 = mock.Mock()
        mock_backend_1.replication_type = 'async'
        mock_backend_2 = mock.Mock()
        mock_backend_2.replication_type = 'async'
        self.driver._replication_target_arrays = [mock_backend_1,
                                                  mock_backend_2]
        mock_get_snap.side_effect = [None, REPLICATED_PGSNAPS[0]]

        array, pg_snap = self.driver._find_async_failover_target()
        self.assertEqual(mock_backend_2, array)
        self.assertEqual(REPLICATED_PGSNAPS[0], pg_snap)

    @mock.patch(BASE_DRIVER_OBJ + '._get_latest_replicated_pg_snap')
    def test_find_async_failover_target_no_pgsnap(
            self, mock_get_snap):
        mock_backend = mock.Mock()
        mock_backend.replication_type = 'async'
        self.driver._replication_target_arrays = [mock_backend]
        mock_get_snap.return_value = None

        self.assertRaises(pure.PureDriverException,
                          self.driver._find_async_failover_target)

    @mock.patch(BASE_DRIVER_OBJ + '._get_latest_replicated_pg_snap')
    def test_find_async_failover_target_error_propagates_no_secondary(
            self, mock_get_snap):
        mock_backend = mock.Mock()
        mock_backend.replication_type = 'async'
        self.driver._replication_target_arrays = [mock_backend]
        self.assert_error_propagates(
            [mock_get_snap],
            self.driver._find_async_failover_target
        )

    def test_find_sync_failover_target_success(self):
        secondary = mock.MagicMock()
        self.driver._active_cluster_target_arrays = [secondary]
        secondary.get_pod.return_value = CINDER_POD
        secondary.array_id = CINDER_POD['arrays'][1]['array_id']

        actual_secondary = self.driver._find_sync_failover_target()
        self.assertEqual(secondary, actual_secondary)

    def test_find_sync_failover_target_no_ac_arrays(self):
        self.driver._active_cluster_target_arrays = []
        actual_secondary = self.driver._find_sync_failover_target()
        self.assertIsNone(actual_secondary)

    def test_find_sync_failover_target_fail_to_get_pod(self):
        secondary = mock.MagicMock()
        self.driver._active_cluster_target_arrays = [secondary]
        secondary.get_pod.side_effect = self.purestorage_module.PureHTTPError(
            'error getting pod status')
        secondary.array_id = CINDER_POD['arrays'][1]['array_id']

        actual_secondary = self.driver._find_sync_failover_target()
        self.assertIsNone(actual_secondary)

    def test_find_sync_failover_target_pod_status_error(self):
        secondary = mock.MagicMock()
        self.driver._active_cluster_target_arrays = [secondary]
        POD_WITH_ERR = deepcopy(CINDER_POD)
        POD_WITH_ERR['arrays'][1]['status'] = 'error'
        secondary.get_pod.return_value = POD_WITH_ERR
        secondary.array_id = CINDER_POD['arrays'][1]['array_id']

        actual_secondary = self.driver._find_sync_failover_target()
        self.assertIsNone(actual_secondary)

    def test_enable_async_replication_if_needed_success(self):
        repl_extra_specs = {
            'replication_type': '<in> async',
            'replication_enabled': '<is> true',
        }
        vol, vol_name = self.new_fake_vol(type_extra_specs=repl_extra_specs)
        self.driver._enable_async_replication_if_needed(self.array, vol)

        self.array.set_pgroup.assert_called_with(
            self.driver._replication_pg_name,
            addvollist=[vol_name]
        )

    def test_enable_async_replication_if_needed_not_repl_type(self):
        vol_type = fake_volume.fake_volume_type_obj(mock.MagicMock())
        vol_obj = fake_volume.fake_volume_obj(mock.MagicMock())
        with mock.patch('cinder.objects.VolumeType.get_by_id') as mock_type:
            mock_type.return_value = vol_type
            self.driver._enable_async_replication_if_needed(self.array,
                                                            vol_obj)
        self.assertFalse(self.array.set_pgroup.called)

    def test_enable_async_replication_if_needed_already_repl(self):
        repl_extra_specs = {
            'replication_type': '<in> async',
            'replication_enabled': '<is> true',
        }
        vol, vol_name = self.new_fake_vol(type_extra_specs=repl_extra_specs)
        self.array.set_pgroup.side_effect = FakePureStorageHTTPError(
            code=http.client.BAD_REQUEST, text='already belongs to')
        self.driver._enable_async_replication_if_needed(self.array, vol)
        self.array.set_pgroup.assert_called_with(
            self.driver._replication_pg_name,
            addvollist=[vol_name]
        )

    def test_enable_async_replication_if_needed_error_propagates(self):
        repl_extra_specs = {
            'replication_type': '<in> async',
            'replication_enabled': '<is> true',
        }
        vol, _ = self.new_fake_vol(type_extra_specs=repl_extra_specs)
        self.driver._enable_async_replication_if_needed(self.array, vol)
        self.assert_error_propagates(
            [self.array.set_pgroup],
            self.driver._enable_async_replication,
            self.array, vol
        )

    @mock.patch(BASE_DRIVER_OBJ + '._get_flasharray')
    @mock.patch(BASE_DRIVER_OBJ + '._find_async_failover_target')
    def test_failover_async(self, mock_find_failover_target, mock_get_array):
        secondary_device_id = 'foo'
        self.async_array2.backend_id = secondary_device_id
        self.driver._replication_target_arrays = [self.async_array2]

        array2_v1_3 = mock.Mock()
        array2_v1_3.backend_id = secondary_device_id
        array2_v1_3.array_name = GET_ARRAY_SECONDARY['array_name']
        array2_v1_3.array_id = GET_ARRAY_SECONDARY['id']
        array2_v1_3.version = '1.3'
        mock_get_array.return_value = array2_v1_3

        target_array = self.async_array2
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
        expected_updates = [
            {
                'updates': {
                    'replication_status': fields.ReplicationStatus.FAILED_OVER
                },
                'volume_id': '1e5177e7-95e5-4a0f-b170-e45f4b469f6a'
            },
            {
                'updates': {
                    'replication_status': fields.ReplicationStatus.FAILED_OVER
                },
                'volume_id': '43a09914-e495-475f-b862-0bda3c8918e4'
            },
            {
                'updates': {
                    'replication_status': fields.ReplicationStatus.FAILED_OVER
                },
                'volume_id': '1b1cf149-219c-44ac-aee3-13121a7f86a7'
            }
        ]
        self.assertEqual(expected_updates, volume_updates)

        calls = []
        for snap in REPLICATED_VOLUME_SNAPS:
            vol_name = snap['name'].split('.')[-1]
            calls.append(mock.call(
                snap['name'],
                vol_name,
                overwrite=True
            ))
        target_array.copy_volume.assert_has_calls(calls, any_order=True)

    @mock.patch(BASE_DRIVER_OBJ + '._find_sync_failover_target')
    def test_failover_sync(self, mock_find_failover_target):
        secondary_device_id = 'foo'
        mock_secondary = mock.MagicMock()
        mock_secondary.backend_id = secondary_device_id
        mock_secondary.replication_type = 'sync'
        self.driver._replication_target_arrays = [mock_secondary]
        mock_find_failover_target.return_value = mock_secondary

        context = mock.MagicMock()

        sync_repl_extra_specs = {
            'replication_type': '<in> sync',
            'replication_enabled': '<is> true',
        }
        sync_replicated_vol, sync_replicated_vol_name = self.new_fake_vol(
            type_extra_specs=sync_repl_extra_specs,
            spec={'id': fake.VOLUME_ID}
        )
        async_repl_extra_specs = {
            'replication_type': '<in> async',
            'replication_enabled': '<is> true',
        }
        async_replicated_vol, _ = self.new_fake_vol(
            type_extra_specs=async_repl_extra_specs,
            spec={'id': fake.VOLUME2_ID}
        )
        not_replicated_vol, _ = self.new_fake_vol(
            spec={'id': fake.VOLUME3_ID}
        )
        not_replicated_vol2, _ = self.new_fake_vol(
            spec={'id': fake.VOLUME4_ID}
        )

        mock_secondary.list_volumes.return_value = [
            {"name": sync_replicated_vol_name}
        ]

        new_active_id, volume_updates, __ = self.driver.failover_host(
            context,
            [
                not_replicated_vol,
                async_replicated_vol,
                sync_replicated_vol,
                not_replicated_vol2
            ],
            None,
            []
        )

        self.assertEqual(secondary_device_id, new_active_id)

        # only expect the sync rep'd vol to make it through the failover
        expected_updates = [
            {
                'updates': {
                    'status': fields.VolumeStatus.ERROR
                },
                'volume_id': not_replicated_vol.id
            },
            {
                'updates': {
                    'status': fields.VolumeStatus.ERROR
                },
                'volume_id': async_replicated_vol.id
            },
            {
                'updates': {
                    'replication_status': fields.ReplicationStatus.FAILED_OVER
                },
                'volume_id': sync_replicated_vol.id
            },
            {
                'updates': {
                    'status': fields.VolumeStatus.ERROR
                },
                'volume_id': not_replicated_vol2.id
            },
        ]
        self.assertEqual(expected_updates, volume_updates)

    @mock.patch(BASE_DRIVER_OBJ + '._get_flasharray')
    @mock.patch(BASE_DRIVER_OBJ + '._find_async_failover_target')
    def test_async_failover_error_propagates(self, mock_find_failover_target,
                                             mock_get_array):
        mock_find_failover_target.return_value = (
            self.async_array2,
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
             self.async_array2.copy_volume],
            self.driver.failover_host,
            mock.Mock(), REPLICATED_VOLUME_OBJS, None
        )

    def test_disable_replication_success(self):
        vol, vol_name = self.new_fake_vol()
        self.driver._disable_async_replication(vol)
        self.array.set_pgroup.assert_called_with(
            self.driver._replication_pg_name,
            remvollist=[vol_name]
        )

    def test_disable_replication_error_propagates(self):
        vol, _ = self.new_fake_vol()
        self.assert_error_propagates(
            [self.array.set_pgroup],
            self.driver._disable_async_replication,
            vol
        )

    def test_disable_replication_already_disabled(self):
        self.array.set_pgroup.side_effect = FakePureStorageHTTPError(
            code=http.client.BAD_REQUEST, text='could not be found')
        vol, vol_name = self.new_fake_vol()
        self.driver._disable_async_replication(vol)
        self.array.set_pgroup.assert_called_with(
            self.driver._replication_pg_name,
            remvollist=[vol_name]
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

    def test_get_flasharray_with_request_kwargs_success(self):
        san_ip = '1.2.3.4'
        api_token = 'abcdef'
        self.purestorage_module.FlashArray.return_value = mock.MagicMock()
        self.purestorage_module.VERSION = "1.17.0"

        self.driver._get_flasharray(san_ip,
                                    api_token,
                                    request_kwargs={"some": "arg"})
        self.purestorage_module.FlashArray.assert_called_with(
            san_ip,
            api_token=api_token,
            rest_version=None,
            verify_https=None,
            ssl_cert=None,
            user_agent=self.driver._user_agent,
            request_kwargs={"some": "arg"}
        )

    def test_get_flasharray_with_request_kwargs_version_too_old(self):
        san_ip = '1.2.3.4'
        api_token = 'abcdef'
        self.purestorage_module.FlashArray.return_value = mock.MagicMock()
        self.purestorage_module.VERSION = "1.10.0"

        self.driver._get_flasharray(san_ip,
                                    api_token,
                                    request_kwargs={"some": "arg"})
        self.purestorage_module.FlashArray.assert_called_with(
            san_ip,
            api_token=api_token,
            rest_version=None,
            verify_https=None,
            ssl_cert=None,
            user_agent=self.driver._user_agent
        )

    def test_get_wwn(self):
        vol = {'created': '2019-01-28T14:16:54Z',
               'name': 'volume-fdc9892f-5af0-47c8-9d4a-5167ac29dc98-cinder',
               'serial': '9714B5CB91634C470002B2C8',
               'size': 3221225472,
               'source': 'volume-a366b1ba-ec27-4ca3-9051-c301b75bc778-cinder'}
        self.array.get_volume.return_value = vol
        returned_wwn = self.driver._get_wwn(vol['name'])
        expected_wwn = '3624a93709714b5cb91634c470002b2c8'
        self.assertEqual(expected_wwn, returned_wwn)

    @mock.patch.object(qos_specs, "get_qos_specs")
    def test_get_qos_settings_from_specs_id(self, mock_get_qos_specs):
        qos = qos_specs.create(mock.MagicMock(), "qos-iops-bws", QOS_IOPS_BWS)
        mock_get_qos_specs.return_value = qos

        voltype = fake_volume.fake_volume_type_obj(mock.MagicMock())
        voltype.qos_specs_id = qos.id
        voltype.extra_specs = QOS_IOPS_BWS_2  # test override extra_specs

        specs = self.driver._get_qos_settings(voltype)
        self.assertEqual(specs["maxIOPS"],
                         int(QOS_IOPS_BWS["maxIOPS"]))
        self.assertEqual(specs["maxBWS"],
                         int(QOS_IOPS_BWS["maxBWS"]) * 1024 * 1024)

    def test_get_qos_settings_from_extra_specs(self):
        voltype = fake_volume.fake_volume_type_obj(mock.MagicMock())
        voltype.extra_specs = QOS_IOPS_BWS

        specs = self.driver._get_qos_settings(voltype)
        self.assertEqual(specs["maxIOPS"],
                         int(QOS_IOPS_BWS["maxIOPS"]))
        self.assertEqual(specs["maxBWS"],
                         int(QOS_IOPS_BWS["maxBWS"]) * 1024 * 1024)

    def test_get_qos_settings_set_zeros(self):
        voltype = fake_volume.fake_volume_type_obj(mock.MagicMock())
        voltype.extra_specs = QOS_ZEROS
        specs = self.driver._get_qos_settings(voltype)
        self.assertEqual(specs["maxIOPS"], 0)
        self.assertEqual(specs["maxBWS"], 0)

    def test_get_qos_settings_set_one(self):
        voltype = fake_volume.fake_volume_type_obj(mock.MagicMock())
        voltype.extra_specs = QOS_IOPS
        specs = self.driver._get_qos_settings(voltype)
        self.assertEqual(specs["maxIOPS"], int(QOS_IOPS["maxIOPS"]))
        self.assertEqual(specs["maxBWS"], 0)

        voltype.extra_specs = QOS_BWS
        specs = self.driver._get_qos_settings(voltype)
        self.assertEqual(specs["maxIOPS"], 0)
        self.assertEqual(specs["maxBWS"],
                         int(QOS_BWS["maxBWS"]) * 1024 * 1024)

    def test_get_qos_settings_invalid(self):
        voltype = fake_volume.fake_volume_type_obj(mock.MagicMock())
        voltype.extra_specs = QOS_INVALID
        self.assertRaises(exception.InvalidQoSSpecs,
                          self.driver._get_qos_settings,
                          voltype)

    @mock.patch(BASE_DRIVER_OBJ + "._add_to_group_if_needed")
    @mock.patch(BASE_DRIVER_OBJ + "._get_replication_type_from_vol_type")
    @mock.patch.object(qos_specs, "get_qos_specs")
    @mock.patch.object(volume_types, 'get_volume_type')
    def test_create_volume_with_qos(self, mock_get_volume_type,
                                    mock_get_qos_specs,
                                    mock_get_repl_type,
                                    mock_add_to_group):
        qos = qos_specs.create(mock.MagicMock(), "qos-iops-bws", QOS_IOPS_BWS)
        vol, vol_name = self.new_fake_vol(spec={"size": 1},
                                          type_qos_specs_id=qos.id)

        mock_get_volume_type.return_value = vol.volume_type
        self.array._list_available_rest_versions.return_value = [
            '1.0', '1.1', '1.2', '1.3', '1.4', '1.5', '1.6', '1.7', '1.8',
            '1.9', '1.10', '1.11', '1.12', '1.13', '1.14', '1.15', '1.16',
            '1.17', '1.18', '1.19']
        mock_get_qos_specs.return_value = qos
        mock_get_repl_type.return_value = None

        self.driver.create_volume(vol)
        self.array.create_volume.assert_called_with(
            vol_name, 1 * units.Gi,
            iops_limit=int(QOS_IOPS_BWS["maxIOPS"]),
            bandwidth_limit=int(QOS_IOPS_BWS["maxBWS"]) * 1024 * 1024)
        mock_add_to_group.assert_called_once_with(vol,
                                                  vol_name)
        self.assert_error_propagates([self.array.create_volume],
                                     self.driver.create_volume, vol)

    @mock.patch(BASE_DRIVER_OBJ + "._add_to_group_if_needed")
    @mock.patch(BASE_DRIVER_OBJ + "._get_replication_type_from_vol_type")
    @mock.patch.object(qos_specs, "get_qos_specs")
    @mock.patch.object(volume_types, 'get_volume_type')
    def test_create_volume_from_snapshot_with_qos(self, mock_get_volume_type,
                                                  mock_get_qos_specs,
                                                  mock_get_repl_type,
                                                  mock_add_to_group):
        srcvol, _ = self.new_fake_vol()
        snap = fake_snapshot.fake_snapshot_obj(mock.MagicMock(), volume=srcvol)
        snap_name = snap["volume_name"] + "-cinder." + snap["name"]
        qos = qos_specs.create(mock.MagicMock(), "qos-iops-bws", QOS_IOPS_BWS)
        vol, vol_name = self.new_fake_vol(set_provider_id=False,
                                          type_qos_specs_id=qos.id)

        mock_get_volume_type.return_value = vol.volume_type
        self.array._list_available_rest_versions.return_value = [
            '1.0', '1.1', '1.2', '1.3', '1.4', '1.5', '1.6', '1.7', '1.8',
            '1.9', '1.10', '1.11', '1.12', '1.13', '1.14', '1.15', '1.16',
            '1.17', '1.18', '1.19']
        mock_get_qos_specs.return_value = qos
        mock_get_repl_type.return_value = None

        self.driver.create_volume_from_snapshot(vol, snap)
        self.array.copy_volume.assert_called_with(snap_name, vol_name)
        self.array.set_volume.assert_called_with(
            vol_name,
            iops_limit=int(QOS_IOPS_BWS["maxIOPS"]),
            bandwidth_limit=int(QOS_IOPS_BWS["maxBWS"]) * 1024 * 1024)
        self.assertFalse(self.array.extend_volume.called)
        mock_add_to_group.assert_called_once_with(vol, vol_name)
        self.assert_error_propagates(
            [self.array.copy_volume],
            self.driver.create_volume_from_snapshot, vol, snap)
        self.assertFalse(self.array.extend_volume.called)

    @mock.patch.object(qos_specs, "get_qos_specs")
    @mock.patch.object(volume_types, 'get_volume_type')
    def test_manage_existing_with_qos(self, mock_get_volume_type,
                                      mock_get_qos_specs):
        ref_name = 'vol1'
        volume_ref = {'name': ref_name}
        qos = qos_specs.create(mock.MagicMock(), "qos-iops-bws", QOS_IOPS_BWS)
        vol, vol_name = self.new_fake_vol(set_provider_id=False,
                                          type_qos_specs_id=qos.id)

        mock_get_volume_type.return_value = vol.volume_type
        mock_get_qos_specs.return_value = qos
        self.array.list_volume_private_connections.return_value = []
        self.array._list_available_rest_versions.return_value = [
            '1.0', '1.1', '1.2', '1.3', '1.4', '1.5', '1.6', '1.7', '1.8',
            '1.9', '1.10', '1.11', '1.12', '1.13', '1.14', '1.15', '1.16',
            '1.17', '1.18', '1.19']

        self.driver.manage_existing(vol, volume_ref)
        self.array.list_volume_private_connections.assert_called_with(ref_name)
        self.array.rename_volume.assert_called_with(ref_name, vol_name)
        self.array.set_volume.assert_called_with(
            vol_name,
            iops_limit=int(QOS_IOPS_BWS["maxIOPS"]),
            bandwidth_limit=int(QOS_IOPS_BWS["maxBWS"]) * 1024 * 1024)

    def test_retype_qos(self):
        mock_context = mock.MagicMock()
        vol, vol_name = self.new_fake_vol()
        qos = qos_specs.create(mock.MagicMock(), "qos-iops-bws", QOS_IOPS_BWS)
        new_type = fake_volume.fake_volume_type_obj(mock_context)
        new_type.qos_specs_id = qos.id

        self.array._list_available_rest_versions.return_value = [
            '1.0', '1.1', '1.2', '1.3', '1.4', '1.5', '1.6', '1.7', '1.8',
            '1.9', '1.10', '1.11', '1.12', '1.13', '1.14', '1.15', '1.16',
            '1.17', '1.18', '1.19']
        get_voltype = "cinder.objects.volume_type.VolumeType.get_by_name_or_id"
        with mock.patch(get_voltype) as mock_get_vol_type:
            mock_get_vol_type.return_value = new_type
            did_retype, model_update = self.driver.retype(
                mock_context,
                vol,
                new_type,
                None,  # ignored by driver
                None,  # ignored by driver
            )

        self.array.set_volume.assert_called_with(
            vol_name,
            iops_limit=int(QOS_IOPS_BWS["maxIOPS"]),
            bandwidth_limit=int(QOS_IOPS_BWS["maxBWS"]) * 1024 * 1024)
        self.assertTrue(did_retype)
        self.assertIsNone(model_update)

    def test_retype_qos_reset_iops(self):
        mock_context = mock.MagicMock()
        vol, vol_name = self.new_fake_vol()
        new_type = fake_volume.fake_volume_type_obj(mock_context)

        self.array._list_available_rest_versions.return_value = [
            '1.0', '1.1', '1.2', '1.3', '1.4', '1.5', '1.6', '1.7', '1.8',
            '1.9', '1.10', '1.11', '1.12', '1.13', '1.14', '1.15', '1.16',
            '1.17', '1.18', '1.19']
        get_voltype = "cinder.objects.volume_type.VolumeType.get_by_name_or_id"
        with mock.patch(get_voltype) as mock_get_vol_type:
            mock_get_vol_type.return_value = new_type
            did_retype, model_update = self.driver.retype(
                mock_context,
                vol,
                new_type,
                None,  # ignored by driver
                None,  # ignored by driver
            )

        self.array.set_volume.assert_called_with(
            vol_name,
            iops_limit="",
            bandwidth_limit="")
        self.assertTrue(did_retype)
        self.assertIsNone(model_update)


class PureISCSIDriverTestCase(PureBaseSharedDriverTestCase):

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
        self.assertEqual([], real_result)
        self.array.list_hosts.return_value.append(good_host)
        real_result = self.driver._get_host(self.array, ISCSI_CONNECTOR)
        self.assertEqual([good_host], real_result)
        self.assert_error_propagates([self.array.list_hosts],
                                     self.driver._get_host,
                                     self.array,
                                     ISCSI_CONNECTOR)

    @mock.patch(ISCSI_DRIVER_OBJ + "._get_wwn")
    @mock.patch(ISCSI_DRIVER_OBJ + "._connect")
    @mock.patch(ISCSI_DRIVER_OBJ + "._get_target_iscsi_ports")
    def test_initialize_connection(self, mock_get_iscsi_ports,
                                   mock_connection, mock_get_wwn):
        vol, vol_name = self.new_fake_vol()
        mock_get_iscsi_ports.return_value = ISCSI_PORTS
        mock_get_wwn.return_value = '3624a93709714b5cb91634c470002b2c8'
        lun = 1
        connection = {
            "vol": vol_name,
            "lun": lun,
        }
        mock_connection.return_value = connection
        result = deepcopy(ISCSI_CONNECTION_INFO)

        real_result = self.driver.initialize_connection(vol,
                                                        ISCSI_CONNECTOR)
        self.assertDictEqual(result, real_result)
        mock_get_iscsi_ports.assert_called_with(self.array)
        mock_connection.assert_called_with(self.array, vol_name,
                                           ISCSI_CONNECTOR, None, None)
        self.assert_error_propagates([mock_get_iscsi_ports, mock_connection],
                                     self.driver.initialize_connection,
                                     vol, ISCSI_CONNECTOR)

    @mock.patch(ISCSI_DRIVER_OBJ + "._get_wwn")
    @mock.patch(ISCSI_DRIVER_OBJ + "._connect")
    @mock.patch(ISCSI_DRIVER_OBJ + "._get_target_iscsi_ports")
    def test_initialize_connection_ipv6(self, mock_get_iscsi_ports,
                                        mock_connection, mock_get_wwn):
        vol, vol_name = self.new_fake_vol()
        mock_get_iscsi_ports.return_value = ISCSI_PORTS
        mock_get_wwn.return_value = '3624a93709714b5cb91634c470002b2c8'
        lun = 1
        connection = {
            "vol": vol_name,
            "lun": lun,
        }
        mock_connection.return_value = connection

        self.mock_config.pure_iscsi_cidr = ISCSI_CIDR_V6
        result = deepcopy(ISCSI_CONNECTION_INFO_V6)

        real_result = self.driver.initialize_connection(vol,
                                                        ISCSI_CONNECTOR)
        self.assertDictEqual(result, real_result)
        mock_get_iscsi_ports.assert_called_with(self.array)
        mock_connection.assert_called_with(self.array, vol_name,
                                           ISCSI_CONNECTOR, None, None)
        self.assert_error_propagates([mock_get_iscsi_ports, mock_connection],
                                     self.driver.initialize_connection,
                                     vol, ISCSI_CONNECTOR)

    @mock.patch(ISCSI_DRIVER_OBJ + "._get_wwn")
    @mock.patch(ISCSI_DRIVER_OBJ + "._connect")
    @mock.patch(ISCSI_DRIVER_OBJ + "._get_target_iscsi_ports")
    def test_initialize_connection_uniform_ac(self, mock_get_iscsi_ports,
                                              mock_connection, mock_get_wwn):
        repl_extra_specs = {
            'replication_type': '<in> sync',
            'replication_enabled': '<is> true',
        }
        vol, vol_name = self.new_fake_vol(type_extra_specs=repl_extra_specs)
        mock_get_iscsi_ports.side_effect = [ISCSI_PORTS, AC_ISCSI_PORTS]
        mock_get_wwn.return_value = '3624a93709714b5cb91634c470002b2c8'
        mock_connection.side_effect = [
            {
                "vol": vol_name,
                "lun": 1,
            },
            {
                "vol": vol_name,
                "lun": 5,
            }
        ]
        result = deepcopy(ISCSI_CONNECTION_INFO_AC)

        self.driver._is_active_cluster_enabled = True
        mock_secondary = mock.MagicMock()
        self.driver._uniform_active_cluster_target_arrays = [mock_secondary]

        real_result = self.driver.initialize_connection(vol,
                                                        ISCSI_CONNECTOR)
        self.assertDictEqual(result, real_result)
        mock_get_iscsi_ports.assert_has_calls([
            mock.call(self.array),
            mock.call(mock_secondary),
        ])
        mock_connection.assert_has_calls([
            mock.call(self.array, vol_name, ISCSI_CONNECTOR, None, None),
            mock.call(mock_secondary, vol_name, ISCSI_CONNECTOR, None, None),
        ])

    @mock.patch(ISCSI_DRIVER_OBJ + "._get_wwn")
    @mock.patch(ISCSI_DRIVER_OBJ + "._connect")
    @mock.patch(ISCSI_DRIVER_OBJ + "._get_target_iscsi_ports")
    def test_initialize_connection_uniform_ac_cidr(self,
                                                   mock_get_iscsi_ports,
                                                   mock_connection,
                                                   mock_get_wwn):
        repl_extra_specs = {
            'replication_type': '<in> sync',
            'replication_enabled': '<is> true',
        }
        vol, vol_name = self.new_fake_vol(type_extra_specs=repl_extra_specs)
        mock_get_iscsi_ports.side_effect = [ISCSI_PORTS, AC_ISCSI_PORTS]
        mock_get_wwn.return_value = '3624a93709714b5cb91634c470002b2c8'
        mock_connection.side_effect = [
            {
                "vol": vol_name,
                "lun": 1,
            },
            {
                "vol": vol_name,
                "lun": 5,
            }
        ]
        result = deepcopy(ISCSI_CONNECTION_INFO_AC_FILTERED)

        self.driver._is_active_cluster_enabled = True
        # Set up some CIDRs to block: this will block only one of the
        # ActiveCluster addresses from above, so we should check that we only
        # get four+three results back
        self.driver.configuration.pure_iscsi_cidr = ISCSI_CIDR_FILTERED
        mock_secondary = mock.MagicMock()
        self.driver._uniform_active_cluster_target_arrays = [mock_secondary]

        real_result = self.driver.initialize_connection(vol,
                                                        ISCSI_CONNECTOR)
        self.assertDictEqual(result, real_result)
        mock_get_iscsi_ports.assert_has_calls([
            mock.call(self.array),
            mock.call(mock_secondary),
        ])
        mock_connection.assert_has_calls([
            mock.call(self.array, vol_name, ISCSI_CONNECTOR, None, None),
            mock.call(mock_secondary, vol_name, ISCSI_CONNECTOR, None, None),
        ])

    @mock.patch(ISCSI_DRIVER_OBJ + "._get_wwn")
    @mock.patch(ISCSI_DRIVER_OBJ + "._connect")
    @mock.patch(ISCSI_DRIVER_OBJ + "._get_target_iscsi_ports")
    def test_initialize_connection_uniform_ac_cidrs(self,
                                                    mock_get_iscsi_ports,
                                                    mock_connection,
                                                    mock_get_wwn):
        repl_extra_specs = {
            'replication_type': '<in> sync',
            'replication_enabled': '<is> true',
        }
        vol, vol_name = self.new_fake_vol(type_extra_specs=repl_extra_specs)
        mock_get_iscsi_ports.side_effect = [ISCSI_PORTS, AC_ISCSI_PORTS]
        mock_get_wwn.return_value = '3624a93709714b5cb91634c470002b2c8'
        mock_connection.side_effect = [
            {
                "vol": vol_name,
                "lun": 1,
            },
            {
                "vol": vol_name,
                "lun": 5,
            }
        ]
        result = deepcopy(ISCSI_CONNECTION_INFO_AC_FILTERED_LIST)

        self.driver._is_active_cluster_enabled = True
        # Set up some CIDRs to block: this will allow only 2 addresses from
        # each host of the ActiveCluster, so we should check that we only
        # get two+two results back
        self.driver.configuration.pure_iscsi = ISCSI_CIDR
        self.driver.configuration.pure_iscsi_cidr_list = ISCSI_CIDRS_FILTERED
        mock_secondary = mock.MagicMock()
        self.driver._uniform_active_cluster_target_arrays = [mock_secondary]

        real_result = self.driver.initialize_connection(vol,
                                                        ISCSI_CONNECTOR)
        self.assertDictEqual(result, real_result)
        mock_get_iscsi_ports.assert_has_calls([
            mock.call(self.array),
            mock.call(mock_secondary),
        ])
        mock_connection.assert_has_calls([
            mock.call(self.array, vol_name, ISCSI_CONNECTOR, None, None),
            mock.call(mock_secondary, vol_name, ISCSI_CONNECTOR, None, None),
        ])

    @mock.patch(ISCSI_DRIVER_OBJ + "._get_wwn")
    @mock.patch(ISCSI_DRIVER_OBJ + "._get_chap_credentials")
    @mock.patch(ISCSI_DRIVER_OBJ + "._connect")
    @mock.patch(ISCSI_DRIVER_OBJ + "._get_target_iscsi_ports")
    def test_initialize_connection_with_auth(self, mock_get_iscsi_ports,
                                             mock_connection,
                                             mock_get_chap_creds,
                                             mock_get_wwn):
        vol, vol_name = self.new_fake_vol()
        auth_type = "CHAP"
        chap_username = ISCSI_CONNECTOR["host"]
        chap_password = "password"
        mock_get_iscsi_ports.return_value = ISCSI_PORTS
        mock_get_wwn.return_value = '3624a93709714b5cb91634c470002b2c8'
        mock_connection.return_value = {
            "vol": vol_name,
            "lun": 1,
        }
        result = deepcopy(ISCSI_CONNECTION_INFO)
        result["data"]["auth_method"] = auth_type
        result["data"]["auth_username"] = chap_username
        result["data"]["auth_password"] = chap_password

        self.mock_config.use_chap_auth = True
        mock_get_chap_creds.return_value = (chap_username, chap_password)

        # Branch where no credentials were generated
        real_result = self.driver.initialize_connection(vol,
                                                        ISCSI_CONNECTOR)
        mock_connection.assert_called_with(self.array,
                                           vol_name,
                                           ISCSI_CONNECTOR,
                                           chap_username,
                                           chap_password)
        self.assertDictEqual(result, real_result)

        self.assert_error_propagates([mock_get_iscsi_ports, mock_connection],
                                     self.driver.initialize_connection,
                                     vol, ISCSI_CONNECTOR)

    @mock.patch(ISCSI_DRIVER_OBJ + "._get_wwn")
    @mock.patch(ISCSI_DRIVER_OBJ + "._connect")
    @mock.patch(ISCSI_DRIVER_OBJ + "._get_target_iscsi_ports")
    def test_initialize_connection_multipath(self,
                                             mock_get_iscsi_ports,
                                             mock_connection, mock_get_wwn):
        vol, vol_name = self.new_fake_vol()
        mock_get_iscsi_ports.return_value = ISCSI_PORTS
        mock_get_wwn.return_value = '3624a93709714b5cb91634c470002b2c8'
        lun = 1
        connection = {
            "vol": vol_name,
            "lun": lun,
        }
        mock_connection.return_value = connection
        multipath_connector = deepcopy(ISCSI_CONNECTOR)
        multipath_connector["multipath"] = True
        result = deepcopy(ISCSI_CONNECTION_INFO)

        real_result = self.driver.initialize_connection(vol,
                                                        multipath_connector)
        self.assertDictEqual(result, real_result)
        mock_get_iscsi_ports.assert_called_with(self.array)
        mock_connection.assert_called_with(self.array, vol_name,
                                           multipath_connector, None, None)

        multipath_connector["multipath"] = False
        self.driver.initialize_connection(vol, multipath_connector)

    def test_get_target_iscsi_ports(self):
        self.array.list_ports.return_value = ISCSI_PORTS
        ret = self.driver._get_target_iscsi_ports(self.array)
        self.assertEqual(ISCSI_PORTS, ret)

    def test_get_target_iscsi_ports_with_iscsi_and_fc(self):
        self.array.list_ports.return_value = PORTS_WITH
        ret = self.driver._get_target_iscsi_ports(self.array)
        self.assertEqual(ISCSI_PORTS, ret)

    def test_get_target_iscsi_ports_with_no_ports(self):
        # Should raise an exception if there are no ports
        self.array.list_ports.return_value = []
        self.assertRaises(pure.PureDriverException,
                          self.driver._get_target_iscsi_ports,
                          self.array)

    def test_get_target_iscsi_ports_with_only_fc_ports(self):
        # Should raise an exception of there are no iscsi ports
        self.array.list_ports.return_value = PORTS_WITHOUT
        self.assertRaises(pure.PureDriverException,
                          self.driver._get_target_iscsi_ports,
                          self.array)

    @mock.patch(ISCSI_DRIVER_OBJ + "._get_host", autospec=True)
    @mock.patch(ISCSI_DRIVER_OBJ + "._generate_purity_host_name", spec=True)
    def test_connect(self, mock_generate, mock_host):
        vol, vol_name = self.new_fake_vol()
        result = {"vol": vol_name, "lun": 1}

        # Branch where host already exists
        mock_host.return_value = [PURE_HOST]
        self.array.connect_host.return_value = {"vol": vol_name, "lun": 1}
        real_result = self.driver._connect(self.array, vol_name,
                                           ISCSI_CONNECTOR, None, None)
        self.assertEqual(result, real_result)
        mock_host.assert_called_with(self.driver, self.array,
                                     ISCSI_CONNECTOR, remote=False)
        self.assertFalse(mock_generate.called)
        self.assertFalse(self.array.create_host.called)
        self.array.connect_host.assert_called_with(PURE_HOST_NAME, vol_name)

        # Branch where new host is created
        mock_host.return_value = []
        mock_generate.return_value = PURE_HOST_NAME
        real_result = self.driver._connect(self.array, vol_name,
                                           ISCSI_CONNECTOR, None, None)
        mock_host.assert_called_with(self.driver, self.array,
                                     ISCSI_CONNECTOR, remote=False)
        mock_generate.assert_called_with(HOSTNAME)
        self.array.create_host.assert_called_with(PURE_HOST_NAME,
                                                  iqnlist=[INITIATOR_IQN])
        self.assertFalse(self.array.set_host.called)
        self.assertEqual(result, real_result)

        mock_generate.reset_mock()
        self.array.reset_mock()
        self.assert_error_propagates(
            [mock_host, mock_generate, self.array.connect_host,
             self.array.create_host], self.driver._connect, self.array,
            vol_name, ISCSI_CONNECTOR, None, None)

        self.mock_config.use_chap_auth = True
        chap_user = ISCSI_CONNECTOR["host"]
        chap_password = "sOmEseCr3t"

        # Branch where chap is used and credentials already exist
        self.driver._connect(self.array, vol_name, ISCSI_CONNECTOR,
                             chap_user, chap_password)
        self.assertDictEqual(result, real_result)
        self.array.set_host.assert_called_with(PURE_HOST_NAME,
                                               host_user=chap_user,
                                               host_password=chap_password)

        self.array.reset_mock()
        self.mock_config.use_chap_auth = False
        self.mock_config.safe_get.return_value = 'oracle-vm-server'

        self.array._list_available_rest_versions.return_value = [
            '1.0', '1.1', '1.2', '1.3', '1.4', '1.5', '1.6', '1.7', '1.8',
            '1.9', '1.10', '1.11']
        # Branch where we fail due to invalid version for setting personality
        self.assertRaises(pure.PureDriverException, self.driver._connect,
                          self.array, vol_name, ISCSI_CONNECTOR, None, None)
        self.assertFalse(self.array.create_host.called)
        self.assertFalse(self.array.set_host.called)

        self.array._list_available_rest_versions.return_value = [
            '1.0', '1.1', '1.2', '1.3', '1.4', '1.5', '1.6', '1.7', '1.8',
            '1.9', '1.10', '1.11', '1.12', '1.13', '1.14', '1.15', '1.16',
            '1.17', '1.18', '1.19']

        # Branch where personality is set
        self.driver._connect(self.array, vol_name, ISCSI_CONNECTOR,
                             None, None)
        self.assertDictEqual(result, real_result)
        self.array.set_host.assert_called_with(PURE_HOST_NAME,
                                               personality='oracle-vm-server')

    @mock.patch(ISCSI_DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_already_connected(self, mock_host):
        vol, vol_name = self.new_fake_vol()
        mock_host.return_value = [PURE_HOST]
        expected = {"host": PURE_HOST_NAME, "lun": 1}
        self.array.list_volume_private_connections.return_value = \
            [expected, {"host": "extra", "lun": 2}]
        self.array.connect_host.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=http.client.BAD_REQUEST,
                text="Connection already exists"
            )
        actual = self.driver._connect(self.array, vol_name, ISCSI_CONNECTOR,
                                      None, None)
        self.assertEqual(expected, actual)
        self.assertTrue(self.array.connect_host.called)
        self.assertTrue(bool(self.array.list_volume_private_connections))

    @mock.patch(ISCSI_DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_already_connected_list_hosts_empty(self, mock_host):
        vol, vol_name = self.new_fake_vol()
        mock_host.return_value = [PURE_HOST]
        self.array.list_volume_private_connections.return_value = {}
        self.array.connect_host.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=http.client.BAD_REQUEST,
                text="Connection already exists"
            )
        self.assertRaises(pure.PureDriverException, self.driver._connect,
                          self.array, vol_name, ISCSI_CONNECTOR, None, None)
        self.assertTrue(self.array.connect_host.called)
        self.assertTrue(bool(self.array.list_volume_private_connections))

    @mock.patch(ISCSI_DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_already_connected_list_hosts_exception(self, mock_host):
        vol, vol_name = self.new_fake_vol()
        mock_host.return_value = [PURE_HOST]
        self.array.list_volume_private_connections.side_effect = \
            self.purestorage_module.PureHTTPError(code=http.client.BAD_REQUEST,
                                                  text="")
        self.array.connect_host.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=http.client.BAD_REQUEST,
                text="Connection already exists"
            )
        self.assertRaises(self.purestorage_module.PureHTTPError,
                          self.driver._connect, self.array, vol_name,
                          ISCSI_CONNECTOR, None, None)
        self.assertTrue(self.array.connect_host.called)
        self.assertTrue(bool(self.array.list_volume_private_connections))

    @mock.patch(ISCSI_DRIVER_OBJ + "._get_chap_secret_from_init_data")
    @mock.patch(ISCSI_DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_host_deleted(self, mock_host, mock_get_secret):
        vol, vol_name = self.new_fake_vol()
        mock_host.return_value = []
        self.mock_config.use_chap_auth = True
        mock_get_secret.return_value = 'abcdef'

        self.array.set_host.side_effect = (
            self.purestorage_module.PureHTTPError(
                code=http.client.BAD_REQUEST, text='Host does not exist.'))

        # Because we mocked out retry make sure we are raising the right
        # exception to allow for retries to happen.
        self.assertRaises(pure.PureRetryableException,
                          self.driver._connect,
                          self.array, vol_name, ISCSI_CONNECTOR, None, None)

    @mock.patch(ISCSI_DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_iqn_already_in_use(self, mock_host):
        vol, vol_name = self.new_fake_vol()
        mock_host.return_value = []

        self.array.create_host.side_effect = (
            self.purestorage_module.PureHTTPError(
                code=http.client.BAD_REQUEST,
                text='The specified IQN is already in use.'))

        # Because we mocked out retry make sure we are raising the right
        # exception to allow for retries to happen.
        self.assertRaises(pure.PureRetryableException,
                          self.driver._connect,
                          self.array, vol_name, ISCSI_CONNECTOR, None, None)

    @mock.patch(ISCSI_DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_create_host_already_exists(self, mock_host):
        vol, vol_name = self.new_fake_vol()
        mock_host.return_value = []

        self.array.create_host.side_effect = (
            self.purestorage_module.PureHTTPError(
                code=http.client.BAD_REQUEST, text='Host already exists.'))

        # Because we mocked out retry make sure we are raising the right
        # exception to allow for retries to happen.
        self.assertRaises(pure.PureRetryableException,
                          self.driver._connect,
                          self.array, vol_name, ISCSI_CONNECTOR, None, None)

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
            pure.PureDriverException(reason='this should never be hit'),
        ]

        username, password = self.driver._get_chap_credentials(host,
                                                               INITIATOR_IQN)
        self.assertEqual(host, username)
        self.assertEqual(expected_password, password)


class PureFCDriverTestCase(PureBaseSharedDriverTestCase):

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
        self.assertEqual([], actual_result)
        self.array.list_hosts.return_value.append(good_host)
        actual_result = self.driver._get_host(self.array, FC_CONNECTOR)
        self.assertEqual([good_host], actual_result)
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
        self.assertEqual([expected_host], actual_result)

    @mock.patch(FC_DRIVER_OBJ + "._get_wwn")
    @mock.patch(FC_DRIVER_OBJ + "._connect")
    def test_initialize_connection(self, mock_connection, mock_get_wwn):
        vol, vol_name = self.new_fake_vol()
        lookup_service = self.driver._lookup_service
        (lookup_service.get_device_mapping_from_network.
         return_value) = DEVICE_MAPPING
        mock_get_wwn.return_value = '3624a93709714b5cb91634c470002b2c8'
        mock_connection.return_value = {"vol": vol_name,
                                        "lun": 1,
                                        }
        self.array.list_ports.return_value = FC_PORTS
        actual_result = self.driver.initialize_connection(vol, FC_CONNECTOR)
        self.assertDictEqual(FC_CONNECTION_INFO, actual_result)

    @mock.patch(FC_DRIVER_OBJ + "._get_wwn")
    @mock.patch(FC_DRIVER_OBJ + "._connect")
    def test_initialize_connection_uniform_ac(self, mock_connection,
                                              mock_get_wwn):
        repl_extra_specs = {
            'replication_type': '<in> sync',
            'replication_enabled': '<is> true',
        }
        vol, vol_name = self.new_fake_vol(type_extra_specs=repl_extra_specs)
        lookup_service = self.driver._lookup_service
        (lookup_service.get_device_mapping_from_network.
         return_value) = AC_DEVICE_MAPPING
        mock_get_wwn.return_value = '3624a93709714b5cb91634c470002b2c8'
        mock_connection.side_effect = [
            {
                "vol": vol_name,
                "lun": 1,
            },
            {
                "vol": vol_name,
                "lun": 5,
            }
        ]
        self.driver._is_active_cluster_enabled = True
        mock_secondary = mock.MagicMock()
        self.driver._uniform_active_cluster_target_arrays = [mock_secondary]
        self.array.list_ports.return_value = FC_PORTS
        mock_secondary.list_ports.return_value = AC_FC_PORTS
        actual_result = self.driver.initialize_connection(vol, FC_CONNECTOR)
        self.assertDictEqual(FC_CONNECTION_INFO_AC, actual_result)

    @mock.patch(FC_DRIVER_OBJ + "._get_host", autospec=True)
    @mock.patch(FC_DRIVER_OBJ + "._generate_purity_host_name", spec=True)
    def test_connect(self, mock_generate, mock_host):
        vol, vol_name = self.new_fake_vol()
        result = {"vol": vol_name, "lun": 1}

        # Branch where host already exists
        mock_host.return_value = [PURE_HOST]
        self.array.connect_host.return_value = {"vol": vol_name, "lun": 1}
        real_result = self.driver._connect(self.array, vol_name, FC_CONNECTOR)
        self.assertEqual(result, real_result)
        mock_host.assert_called_with(self.driver, self.array, FC_CONNECTOR,
                                     remote=False)
        self.assertFalse(mock_generate.called)
        self.assertFalse(self.array.create_host.called)
        self.array.connect_host.assert_called_with(PURE_HOST_NAME, vol_name)

        # Branch where new host is created
        mock_host.return_value = []
        mock_generate.return_value = PURE_HOST_NAME
        real_result = self.driver._connect(self.array, vol_name, FC_CONNECTOR)
        mock_host.assert_called_with(self.driver, self.array, FC_CONNECTOR,
                                     remote=False)
        mock_generate.assert_called_with(HOSTNAME)
        self.array.create_host.assert_called_with(PURE_HOST_NAME,
                                                  wwnlist={INITIATOR_WWN})
        self.assertEqual(result, real_result)

        mock_generate.reset_mock()
        self.array.reset_mock()
        self.assert_error_propagates(
            [mock_host, mock_generate, self.array.connect_host,
             self.array.create_host],
            self.driver._connect, self.array, vol_name, FC_CONNECTOR)

        self.mock_config.safe_get.return_value = 'oracle-vm-server'
        self.array._list_available_rest_versions.return_value = [
            '1.0', '1.1', '1.2', '1.3', '1.4', '1.5', '1.6', '1.7', '1.8',
            '1.9', '1.10', '1.11']

        # Branch where we fail due to invalid version for setting personality
        self.assertRaises(pure.PureDriverException, self.driver._connect,
                          self.array, vol_name, FC_CONNECTOR)
        self.assertTrue(self.array.create_host.called)
        self.assertFalse(self.array.set_host.called)

        self.array._list_available_rest_versions.return_value = [
            '1.0', '1.1', '1.2', '1.3', '1.4', '1.5', '1.6', '1.7', '1.8',
            '1.9', '1.10', '1.11', '1.12', '1.13', '1.14', '1.15', '1.16',
            '1.17', '1.18', '1.19']

        # Branch where personality is set
        self.driver._connect(self.array, vol_name, FC_CONNECTOR)
        self.assertDictEqual(result, real_result)
        self.array.set_host.assert_called_with(PURE_HOST_NAME,
                                               personality='oracle-vm-server')

    @mock.patch(FC_DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_already_connected(self, mock_host):
        vol, vol_name = self.new_fake_vol()
        mock_host.return_value = [PURE_HOST]
        expected = {"host": PURE_HOST_NAME, "lun": 1}
        self.array.list_volume_private_connections.return_value = \
            [expected, {"host": "extra", "lun": 2}]
        self.array.connect_host.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=http.client.BAD_REQUEST,
                text="Connection already exists"
            )
        actual = self.driver._connect(self.array, vol_name, FC_CONNECTOR)
        self.assertEqual(expected, actual)
        self.assertTrue(self.array.connect_host.called)
        self.assertTrue(bool(self.array.list_volume_private_connections))

    @mock.patch(FC_DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_already_connected_list_hosts_empty(self, mock_host):
        vol, vol_name = self.new_fake_vol()
        mock_host.return_value = [PURE_HOST]
        self.array.list_volume_private_connections.return_value = {}
        self.array.connect_host.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=http.client.BAD_REQUEST,
                text="Connection already exists"
            )
        self.assertRaises(pure.PureDriverException, self.driver._connect,
                          self.array, vol_name, FC_CONNECTOR)
        self.assertTrue(self.array.connect_host.called)
        self.assertTrue(bool(self.array.list_volume_private_connections))

    @mock.patch(FC_DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_already_connected_list_hosts_exception(self, mock_host):
        vol, vol_name = self.new_fake_vol()
        mock_host.return_value = [PURE_HOST]
        self.array.list_volume_private_connections.side_effect = \
            self.purestorage_module.PureHTTPError(code=http.client.BAD_REQUEST,
                                                  text="")
        self.array.connect_host.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=http.client.BAD_REQUEST,
                text="Connection already exists"
            )
        self.assertRaises(self.purestorage_module.PureHTTPError,
                          self.driver._connect, self.array, vol_name,
                          FC_CONNECTOR)
        self.assertTrue(self.array.connect_host.called)
        self.assertTrue(bool(self.array.list_volume_private_connections))

    @mock.patch(FC_DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_wwn_already_in_use(self, mock_host):
        vol, vol_name = self.new_fake_vol()
        mock_host.return_value = []

        self.array.create_host.side_effect = (
            self.purestorage_module.PureHTTPError(
                code=http.client.BAD_REQUEST,
                text='The specified WWN is already in use.'))

        # Because we mocked out retry make sure we are raising the right
        # exception to allow for retries to happen.
        self.assertRaises(pure.PureRetryableException,
                          self.driver._connect,
                          self.array, vol_name, FC_CONNECTOR)

    @mock.patch(FC_DRIVER_OBJ + "._disconnect")
    def test_terminate_connection_uniform_ac(self, mock_disconnect):
        repl_extra_specs = {
            'replication_type': '<in> sync',
            'replication_enabled': '<is> true',
        }
        vol, vol_name = self.new_fake_vol(type_extra_specs=repl_extra_specs)
        fcls = self.driver._lookup_service
        fcls.get_device_mapping_from_network.return_value = AC_DEVICE_MAPPING
        self.driver._is_active_cluster_enabled = True
        mock_secondary = mock.MagicMock()
        self.driver._uniform_active_cluster_target_arrays = [mock_secondary]
        self.array.list_ports.return_value = FC_PORTS
        mock_secondary.list_ports.return_value = AC_FC_PORTS
        mock_disconnect.return_value = False

        self.driver.terminate_connection(vol, FC_CONNECTOR)
        mock_disconnect.assert_has_calls([
            mock.call(mock_secondary, vol, FC_CONNECTOR,
                      is_multiattach=False, remove_remote_hosts=False),
            mock.call(self.array, vol, FC_CONNECTOR,
                      is_multiattach=False, remove_remote_hosts=False)
        ])


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
        volume_utils.get_max_over_subscription_ratio = mock.Mock(
            return_value=expected_ratio)
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
            'multiattach': True,
            'QoS_support': True,
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
            'replication_type': [],
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

    @mock.patch(BASE_DRIVER_OBJ + '._add_volume_to_consistency_group')
    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type')
    def test_add_to_group_if_needed(self, mock_is_cg, mock_add_to_cg):
        mock_is_cg.return_value = False
        volume, vol_name = self.new_fake_vol()
        group, _ = self.new_fake_group()
        volume.group = group
        volume.group_id = group.id

        self.driver._add_to_group_if_needed(volume, vol_name)

        mock_is_cg.assert_called_once_with(group)
        mock_add_to_cg.assert_not_called()

    @mock.patch(BASE_DRIVER_OBJ + '._add_volume_to_consistency_group')
    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type')
    def test_add_to_group_if_needed_with_cg(self, mock_is_cg, mock_add_to_cg):
        mock_is_cg.return_value = True
        volume, vol_name = self.new_fake_vol()
        group, _ = self.new_fake_group()
        volume.group = group
        volume.group_id = group.id

        self.driver._add_to_group_if_needed(volume, vol_name)

        mock_is_cg.assert_called_once_with(group)
        mock_add_to_cg.assert_called_once_with(
            group,
            vol_name
        )

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type')
    def test_create_group(self, mock_is_cg):
        mock_is_cg.return_value = False
        group = fake_group.fake_group_type_obj(None)
        self.assertRaises(
            NotImplementedError,
            self.driver.create_group,
            self.mock_context, group
        )
        mock_is_cg.assert_called_once_with(group)

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type')
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

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type')
    def test_update_group(self, mock_is_cg):
        mock_is_cg.return_value = False
        group = mock.MagicMock()
        self.assertRaises(
            NotImplementedError,
            self.driver.update_group,
            self.mock_context, group
        )
        mock_is_cg.assert_called_once_with(group)

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type')
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

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type')
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

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type')
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
