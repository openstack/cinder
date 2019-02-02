# Copyright (c) 2016 Huawei Technologies Co., Ltd.
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
"""Tests for huawei drivers."""
import collections
import copy
import ddt
import json
import mock
import re
import requests
import retrying
import tempfile
from xml.dom import minidom
from xml.etree import ElementTree

from cinder import context
from cinder import exception
from cinder import objects
from cinder.objects import fields
from cinder import test
from cinder.tests.unit import fake_group
from cinder.tests.unit import fake_group_snapshot
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit import utils
from cinder.volume import configuration as conf
from cinder.volume.drivers.huawei import common
from cinder.volume.drivers.huawei import constants
from cinder.volume.drivers.huawei import fc_zone_helper
from cinder.volume.drivers.huawei import huawei_conf
from cinder.volume.drivers.huawei import huawei_driver
from cinder.volume.drivers.huawei import huawei_utils
from cinder.volume.drivers.huawei import hypermetro
from cinder.volume.drivers.huawei import replication
from cinder.volume.drivers.huawei import rest_client
from cinder.volume.drivers.huawei import smartx
from cinder.volume import qos_specs
from cinder.volume import utils as volume_utils
from cinder.volume import volume_types

admin_contex = context.get_admin_context()

vol_attrs = ('id', 'lun_type', 'provider_location', 'metadata')
Volume = collections.namedtuple('Volume', vol_attrs)

PROVIDER_LOCATION = ('{"huawei_lun_id": "11", '
                     '"huawei_lun_wwn": "6643e8c1004c5f6723e9f454003"}')
PROVIDER_LOCATION_WITH_HYPERMETRO = (
    '{"huawei_lun_id": "11", '
    '"huawei_lun_wwn": "6643e8c1004c5f6723e9f454003", '
    '"hypermetro_id": "11", '
    '"remote_lun_id": "1"}')
SNAP_PROVIDER_LOCATION = '{"huawei_snapshot_id": "11"}'

HOST = 'ubuntu001@backend001#OpenStack_Pool'
ENCODE_HOST_NAME = huawei_utils.encode_host_name(HOST)

HOST2 = 'ubuntu002@backend002#OpenStack_Pool'
OLD_ENCODE_HOST_NAME = huawei_utils.old_encode_host_name(HOST2)

ID = '21ec7341-9256-497b-97d9-ef48edcf0635'
ENCODE_NAME = huawei_utils.encode_name(ID)

ID2 = 'ee00eb7c-40dc-4256-bfea-6c3a16ab850d'
OLD_ENCODE_NAME = huawei_utils.old_encode_name(ID2)

METADATA = [{'key': 'huawei_lun_id', 'value': '11'},
            {'key': 'huawei_lun_wwn', 'value': '6643e8c1004c5f6723e9f454003'}]
TEST_PAIR_ID = "3400a30d844d0004"
VOL_METADATA = [{'key': 'hypermetro_id', 'value': '11'},
                {'key': 'remote_lun_id', 'value': '1'}]
ADMIN_METADATA = [{'key': 'huawei_lun_wwn', 'value': 'FAKE_WWN'}]
REPLICA_DRIVER_DATA = ('{"pair_id": "%s", "rmt_lun_id": "1", '
                       '"rmt_lun_wwn": "FAKE_RMT_LUN_WWN"}') % TEST_PAIR_ID

hypermetro_devices = """{
    "remote_device": {
        "RestURL": "http://192.0.2.69:8082/deviceManager/rest",
        "UserName": "admin",
        "UserPassword": "Admin@storage1",
        "StoragePool": "OpenStack_Pool",
        "domain_name": "hypermetro-domain",
        "remote_target_ip": "192.0.2.241"
    }
}
"""

fake_smartx_value = {'smarttier': 'true',
                     'smartcache': 'true',
                     'smartpartition': 'true',
                     'thin_provisioning_support': 'true',
                     'thick_provisioning_support': False,
                     'policy': '2',
                     'cachename': 'cache-test',
                     'partitionname': 'partition-test',
                     }

fake_hypermetro_opts = {'hypermetro': 'true',
                        'smarttier': False,
                        'smartcache': False,
                        'smartpartition': False,
                        'thin_provisioning_support': False,
                        'thick_provisioning_support': False,
                        }

sync_replica_specs = {'capabilities:replication_enabled': '<is> True',
                      'replication_type': '<in> sync'}
async_replica_specs = {'capabilities:replication_enabled': '<is> True',
                       'replication_type': '<in> async'}

replica_hypermetro_specs = {'capabilities:hypermetro': '<is> True',
                            'capabilities:replication_enabled': '<is> True'}

test_host = {'host': 'ubuntu001@backend001#OpenStack_Pool',
             'capabilities': {'smartcache': True,
                              'location_info': '210235G7J20000000000',
                              'QoS_support': True,
                              'pool_name': 'OpenStack_Pool',
                              'timestamp': '2015-07-13T11:41:00.513549',
                              'smartpartition': True,
                              'allocated_capacity_gb': 0,
                              'volume_backend_name': 'HuaweiFCDriver',
                              'free_capacity_gb': 20.0,
                              'driver_version': '1.1.0',
                              'total_capacity_gb': 20.0,
                              'smarttier': True,
                              'hypermetro': True,
                              'reserved_percentage': 0,
                              'vendor_name': None,
                              'thick_provisioning_support': False,
                              'thin_provisioning_support': True,
                              'storage_protocol': 'FC',
                              }
             }

test_new_type = {
    'name': u'new_type',
    'qos_specs_id': None,
    'deleted': False,
    'created_at': None,
    'updated_at': None,
    'extra_specs': {
        'capabilities:smarttier': '<is> true',
        'capabilities:smartcache': '<is> true',
        'capabilities:smartpartition': '<is> true',
        'capabilities:thin_provisioning_support': '<is> true',
        'capabilities:thick_provisioning_support': '<is> False',
        'policy': '2',
        'smartcache:cachename': 'cache-test',
        'smartpartition:partitionname': 'partition-test',
    },
    'is_public': True,
    'deleted_at': None,
    'id': u'530a56e1-a1a4-49f3-ab6c-779a6e5d999f',
    'description': None,
}

test_new_replication_type = {
    'name': u'new_type',
    'qos_specs_id': None,
    'deleted': False,
    'created_at': None,
    'updated_at': None,
    'extra_specs': {
        'capabilities:replication_enabled': '<is> True',
        'replication_type': '<in> sync',
    },
    'is_public': True,
    'deleted_at': None,
    'id': u'530a56e1-a1a4-49f3-ab6c-779a6e5d999f',
    'description': None,
}

test_hypermetro_type = {
    'name': u'new_type',
    'qos_specs_id': None,
    'deleted': False,
    'created_at': None,
    'updated_at': None,
    'extra_specs': {
        'capabilities:hypermetro': '<is> True'
    },
    'is_public': True,
    'deleted_at': None,
    'id': u'550c089b-bfdd-4f7f-86e1-3ba88125555c',
    'description': None,
}

hypermetro_devices = """
{
    "remote_device": {
        "RestURL": "http://192.0.2.69:8082/deviceManager/rest",
        "UserName":"admin",
        "UserPassword":"Admin@storage2",
        "StoragePool":"OpenStack_Pool",
        "domain_name":"hypermetro_test"}
}
"""

FAKE_FIND_POOL_RESPONSE = {'CAPACITY': '985661440',
                           'ID': '0',
                           'TOTALCAPACITY': '985661440'}

FAKE_CREATE_VOLUME_RESPONSE = {"ID": "1",
                               "NAME": "5mFHcBv4RkCcD+JyrWc0SA",
                               "WWN": '6643e8c1004c5f6723e9f454003'}

FakeConnector = {'initiator': 'iqn.1993-08.debian:01:ec2bff7ac3a3',
                 'multipath': False,
                 'wwpns': ['10000090fa0d6754'],
                 'wwnns': ['10000090fa0d6755'],
                 'host': 'ubuntuc',
                 }

smarttier_opts = {'smarttier': 'true',
                  'smartpartition': False,
                  'smartcache': False,
                  'thin_provisioning_support': True,
                  'thick_provisioning_support': False,
                  'policy': '3',
                  'readcachepolicy': '1',
                  'writecachepolicy': None,
                  }

fake_fabric_mapping = {
    'swd1': {
        'target_port_wwn_list': ['2000643e8c4c5f66'],
        'initiator_port_wwn_list': ['10000090fa0d6754']
    }
}

fake_fabric_mapping_no_ports = {
    'swd1': {
        'target_port_wwn_list': [],
        'initiator_port_wwn_list': ['10000090fa0d6754']
    }
}

fake_fabric_mapping_no_wwn = {
    'swd1': {
        'target_port_wwn_list': ['2000643e8c4c5f66'],
        'initiator_port_wwn_list': []
    }
}

CHANGE_OPTS = {'policy': ('1', '2'),
               'partitionid': (['1', 'partition001'], ['2', 'partition002']),
               'cacheid': (['1', 'cache001'], ['2', 'cache002']),
               'qos': (['11', {'MAXIOPS': '100', 'IOType': '1'}],
                       {'MAXIOPS': '100', 'IOType': '2',
                        'MIN': 1, 'LATENCY': 1}),
               'host': ('ubuntu@huawei#OpenStack_Pool',
                        'ubuntu@huawei#OpenStack_Pool'),
               'LUNType': ('0', '1'),
               }

# A fake response of create a host
FAKE_CREATE_HOST_RESPONSE = """
{
    "error": {
        "code": 0
    },
    "data":{"NAME": "ubuntuc001",
            "ID": "1"}
}
"""

FAKE_GET_HOST_RESPONSE = """
{
    "error": {
        "code": 0
    },
    "data":{"NAME": "ubuntuc001",
            "ID": "1",
            "ISADD2HOSTGROUP": "true"}
}
"""

FAKE_PATCH_GET_HOST_RESPONSE = """
{
    "error": {
        "code": 0
    },
    "data":[{"NAME": "ubuntuc001",
            "ID": "1"}]
}
"""

# A fake response of success response storage
FAKE_COMMON_SUCCESS_RESPONSE = """
{
    "error": {
        "code": 0,
        "description": "None"
    },
    "data":{}
}
"""

# A fake response of fail response storage
FAKE_COMMON_FAIL_RESPONSE = """
{
    "error": {
        "code": 50331651,
        "description": "An error occurs to the parameter."
    },
    "data":{}
}
"""

# A fake response of login huawei storage
FAKE_GET_LOGIN_STORAGE_RESPONSE = """
{
    "error": {
        "code": 0
    },
    "data": {
        "username": "admin",
        "iBaseToken": "2001031430",
        "deviceid": "210235G7J20000000000",
        "accountstate": 2
    }
}
"""

# A fake response of login out huawei storage
FAKE_LOGIN_OUT_STORAGE_RESPONSE = """
{
    "error": {
        "code": 0
    },
    "data": {
        "ID": 11
    }
}
"""

# A fake response of mock storage pool info
FAKE_STORAGE_POOL_RESPONSE = """
{
    "error": {
        "code": 0
    },
    "data": [{
        "USERFREECAPACITY": "985661440",
        "ID": "0",
        "NAME": "OpenStack_Pool",
        "USERTOTALCAPACITY": "985661440",
        "TIER0CAPACITY": "100",
        "TIER1CAPACITY": "0",
        "TIER2CAPACITY": "0"
    }]
}
"""

# A fake response of lun or lungroup response
FAKE_LUN_INFO_RESPONSE = """
{
    "error": {
        "code": 0
    },
    "data": {
        "ID": "1",
        "NAME": "5mFHcBv4RkCcD+JyrWc0SA",
        "WWN": "6643e8c1004c5f6723e9f454003",
        "DESCRIPTION": "21ec7341-9256-497b-97d9-ef48edcf0635",
        "HEALTHSTATUS": "1",
        "RUNNINGSTATUS": "27",
        "ALLOCTYPE": "1",
        "CAPACITY": "2097152"
    }
}
"""

# A fake report of mock storage pool info
FAKE_POOLS_UNSUPPORT_REPORT = {
    'pool_name': 'StoragePool',
    'location_info': '2102350BVB10F2000020',
    'QoS_support': False,
    'smartcache': False,
    'thick_provisioning_support': False,
    'splitmirror': False,
    'allocated_capacity_gb': 7,
    'thin_provisioning_support': True,
    'free_capacity_gb': 400.0,
    'smartpartition': False,
    'total_capacity_gb': 400.0,
    'reserved_percentage': 0,
    'max_over_subscription_ratio': 20.0,
    'luncopy': False
}

FAKE_POOLS_SUPPORT_REPORT = {
    'pool_name': 'StoragePool',
    'location_info': '2102350BVB10F2000020',
    'QoS_support': True,
    'smartcache': True,
    'thick_provisioning_support': True,
    'splitmirror': True,
    'allocated_capacity_gb': 7,
    'thin_provisioning_support': True,
    'free_capacity_gb': 400.0,
    'smartpartition': True,
    'total_capacity_gb': 400.0,
    'reserved_percentage': 0,
    'max_over_subscription_ratio': 20.0,
    'luncopy': True,
    'hypermetro': True,
    'consistent_group_snapshot_enabled': True
}

FAKE_LUN_GET_SUCCESS_RESPONSE = """
{
    "error": {
        "code": 0
    },
    "data": {
        "ID": "11",
        "IOCLASSID": "11",
        "NAME": "5mFHcBv4RkCcD+JyrWc0SA",
        "DESCRIPTION": "21ec7341-9256-497b-97d9-ef48edcf0635",
        "RUNNINGSTATUS": "10",
        "HEALTHSTATUS": "1",
        "RUNNINGSTATUS": "27",
        "LUNLIST": "[]",
        "ALLOCTYPE": "1",
        "CAPACITY": "2097152",
        "WRITEPOLICY": "1",
        "MIRRORPOLICY": "0",
        "PREFETCHPOLICY": "1",
        "PREFETCHVALUE": "20",
        "DATATRANSFERPOLICY": "1",
        "READCACHEPOLICY": "2",
        "WRITECACHEPOLICY": "5",
        "OWNINGCONTROLLER": "0B",
        "SMARTCACHEPARTITIONID": "",
        "CACHEPARTITIONID": "",
        "WWN": "6643e8c1004c5f6723e9f454003",
        "PARENTNAME": "OpenStack_Pool"
    }
}
"""

FAKE_QUERY_ALL_LUN_RESPONSE = {
    "error": {
        "code": 0
    },
    "data": [{
        "ID": "11",
        "NAME": ENCODE_NAME,
        "WWN": "6643e8c1004c5f6723e9f454003",
        "DESCRIPTION": "21ec7341-9256-497b-97d9-ef48edcf0635",
        "HEALTHSTATUS": "1",
        "RUNNINGSTATUS": "27",
        "LUNLIST": "[]",
        "ALLOCTYPE": "1",
        "CAPACITY": "2097152",
        "WRITEPOLICY": "1",
        "MIRRORPOLICY": "0",
        "PREFETCHPOLICY": "1",
        "PREFETCHVALUE": "20",
        "DATATRANSFERPOLICY": "1",
        "READCACHEPOLICY": "2",
        "WRITECACHEPOLICY": "5",
        "OWNINGCONTROLLER": "0B",
        "SMARTCACHEPARTITIONID": "",
        "CACHEPARTITIONID": "",
    }]
}

FAKE_LUN_ASSOCIATE_RESPONSE = """
{
    "error":{
        "code":0
    },
    "data":[{
        "ID":"11"
    }]
}
"""

FAKE_QUERY_LUN_GROUP_INFO_RESPONSE = """
{
    "error": {
        "code":0
    },
    "data":[{
        "NAME":"OpenStack_LunGroup_1",
        "DESCRIPTION":"5mFHcBv4RkCcD+JyrWc0SA",
        "ID":"11",
        "TYPE":256
    }]
}
"""

FAKE_QUERY_LUN_GROUP_RESPONSE = """
{
    "error": {
        "code":0
    },
    "data":{
        "NAME":"5mFHcBv4RkCcD+JyrWc0SA",
        "DESCRIPTION":"5mFHcBv4RkCcD+JyrWc0SA",
        "ID":"11",
        "TYPE":256
    }
}
"""

FAKE_QUERY_LUN_GROUP_ASSOCIAT_RESPONSE = """
{
    "error":{
        "code":0
    },
    "data":{
        "NAME":"5mFHcBv4RkCcD+JyrWc0SA",
        "DESCRIPTION":"5mFHcBv4RkCcD+JyrWc0SA",
        "ID":"11",
        "TYPE":256
    }
}
"""

FAKE_LUN_COUNT_RESPONSE = """
{
    "data":{
        "COUNT":"0"
    },
    "error":{
        "code":0,
        "description":"0"
    }
}
"""
# A fake response of snapshot list response
FAKE_SNAPSHOT_LIST_INFO_RESPONSE = {
    "error": {
        "code": 0,
        "description": "0"
    },
    "data": [{
        "ID": "11",
        "NAME": ENCODE_NAME
    }, ]
}


# A fake response of create snapshot response
FAKE_CREATE_SNAPSHOT_INFO_RESPONSE = """
{
    "error": {
        "code": 0
    },
    "data": {
        "ID": "11",
        "NAME": "YheUoRwbSX2BxN7",
        "WWN": "fake-wwn"
    }
}
"""

# A fake response of get snapshot response
FAKE_GET_SNAPSHOT_INFO_RESPONSE = """
{
    "error": {
        "code": 0,
        "description": "0"
    },
    "data": {
        "ID": "11",
        "NAME": "YheUoRwbSX2BxN7",
        "WWN": "fake-wwn"
    }
}
"""

FAKE_SNAPSHOT_COUNT_RESPONSE = """
{
    "data":{
        "COUNT":"2"
    },
    "error":{
        "code":0,
        "description":"0"
    }
}
"""

# A fake response of get iscsi response

FAKE_GET_ISCSI_INFO_RESPONSE = """
{
    "data": [{
        "ETHPORTID": "139267",
        "ID": "0+iqn.oceanstor:21004846fb8ca15f::22004:192.0.2.1,t,0x2005",
        "TPGT": "8197",
        "TYPE": 249
    },
    {
        "ETHPORTID": "139268",
        "ID": "1+iqn.oceanstor:21004846fb8ca15f::22003:192.0.2.2,t,0x2004",
        "TPGT": "8196",
        "TYPE": 249
    }
    ],
    "error": {
        "code": 0,
        "description": "0"
    }
}
"""

# A fake response of get eth info response
FAKE_GET_ETH_INFO_RESPONSE = """
{
    "error": {
        "code": 0
    },
    "data": [{
        "PARENTTYPE": 209,
        "MACADDRESS": "00:22:a1:0a:79:57",
        "ETHNEGOTIATE": "-1",
        "ERRORPACKETS": "0",
        "IPV4ADDR": "192.0.2.2",
        "IPV6GATEWAY": "",
        "IPV6MASK": "0",
        "OVERFLOWEDPACKETS": "0",
        "ISCSINAME": "P0",
        "HEALTHSTATUS": "1",
        "ETHDUPLEX": "2",
        "ID": "16909568",
        "LOSTPACKETS": "0",
        "TYPE": 213,
        "NAME": "P0",
        "INIORTGT": "4",
        "RUNNINGSTATUS": "10",
        "IPV4GATEWAY": "",
        "BONDNAME": "",
        "STARTTIME": "1371684218",
        "SPEED": "1000",
        "ISCSITCPPORT": "0",
        "IPV4MASK": "255.255.0.0",
        "IPV6ADDR": "",
        "LOGICTYPE": "0",
        "LOCATION": "ENG0.A5.P0",
        "MTU": "1500",
        "PARENTID": "1.5"
    },
    {
        "PARENTTYPE": 209,
        "MACADDRESS": "00:22:a1:0a:79:57",
        "ETHNEGOTIATE": "-1",
        "ERRORPACKETS": "0",
        "IPV4ADDR": "192.0.2.1",
        "IPV6GATEWAY": "",
        "IPV6MASK": "0",
        "OVERFLOWEDPACKETS": "0",
        "ISCSINAME": "P0",
        "HEALTHSTATUS": "1",
        "ETHDUPLEX": "2",
        "ID": "16909568",
        "LOSTPACKETS": "0",
        "TYPE": 213,
        "NAME": "P0",
        "INIORTGT": "4",
        "RUNNINGSTATUS": "10",
        "IPV4GATEWAY": "",
        "BONDNAME": "",
        "STARTTIME": "1371684218",
        "SPEED": "1000",
        "ISCSITCPPORT": "0",
        "IPV4MASK": "255.255.0.0",
        "IPV6ADDR": "",
        "LOGICTYPE": "0",
        "LOCATION": "ENG0.A5.P3",
        "MTU": "1500",
        "PARENTID": "1.5"
    }]
}
"""

FAKE_GET_ETH_ASSOCIATE_RESPONSE = """
{
    "error":{
        "code":0
    },
    "data":[{
        "IPV4ADDR": "192.0.2.1",
        "HEALTHSTATUS": "1",
        "RUNNINGSTATUS": "10"
    },
    {
        "IPV4ADDR": "192.0.2.2",
        "HEALTHSTATUS": "1",
        "RUNNINGSTATUS": "10"
    }
    ]
}
"""
# A fake response of get iscsi device info response
FAKE_GET_ISCSI_DEVICE_RESPONSE = """
{
    "error": {
        "code": 0
    },
    "data": [{
        "CMO_ISCSI_DEVICE_NAME": "iqn.2006-08.com.huawei:oceanstor:21000022a:"
    }]
}
"""

# A fake response of get iscsi device info response
FAKE_GET_ALL_HOST_INFO_RESPONSE = """
{
    "error": {
        "code": 0
    },
    "data": [{
        "PARENTTYPE": 245,
        "NAME": "ubuntuc",
        "DESCRIPTION": "",
        "RUNNINGSTATUS": "1",
        "IP": "",
        "PARENTNAME": "",
        "OPERATIONSYSTEM": "0",
        "LOCATION": "",
        "HEALTHSTATUS": "1",
        "MODEL": "",
        "ID": "1",
        "PARENTID": "",
        "NETWORKNAME": "",
        "TYPE": 21
    },
    {
        "PARENTTYPE": 245,
        "NAME": "ubuntu",
        "DESCRIPTION": "",
        "RUNNINGSTATUS": "1",
        "IP": "",
        "PARENTNAME": "",
        "OPERATIONSYSTEM": "0",
        "LOCATION": "",
        "HEALTHSTATUS": "1",
        "MODEL": "",
        "ID": "2",
        "PARENTID": "",
        "NETWORKNAME": "",
        "TYPE": 21
    }]
}
"""

# A fake response of get host or hostgroup info response
FAKE_GET_ALL_HOST_GROUP_INFO_RESPONSE = """
{
    "error": {
        "code": 0
    },
    "data": [{
        "NAME":"ubuntuc",
        "DESCRIPTION":"",
        "ID":"0",
        "TYPE":14
    },
    {"NAME":"OpenStack_HostGroup_1",
     "DESCRIPTION":"",
     "ID":"0",
     "TYPE":14
    }
    ]
}
"""

FAKE_GET_HOST_GROUP_INFO_RESPONSE = """
{
    "error": {
        "code": 0
    },
    "data":{
        "NAME":"ubuntuc",
        "DESCRIPTION":"",
        "ID":"0",
        "TYPE":14
    }
}
"""

# A fake response of lun copy info response
FAKE_GET_LUN_COPY_INFO_RESPONSE = """
{
    "error": {
        "code": 0
    },
    "data": {
        "COPYSTOPTIME": "-1",
        "HEALTHSTATUS": "1",
        "NAME": "w1PSNvu6RumcZMmSh4/l+Q==",
        "RUNNINGSTATUS": "36",
        "DESCRIPTION": "w1PSNvu6RumcZMmSh4/l+Q==",
        "ID": "0",
        "LUNCOPYTYPE": "1",
        "COPYPROGRESS": "0",
        "COPYSPEED": "2",
        "TYPE": 219,
        "COPYSTARTTIME": "-1"
    }
}
"""

# A fake response of lun copy list info response
FAKE_GET_LUN_COPY_LIST_INFO_RESPONSE = """
{
    "error": {
        "code": 0
    },
    "data": [{
        "COPYSTOPTIME": "1372209335",
        "HEALTHSTATUS": "1",
        "NAME": "w1PSNvu6RumcZMmSh4/l+Q==",
        "RUNNINGSTATUS": "40",
        "DESCRIPTION": "w1PSNvu6RumcZMmSh4/l+Q==",
        "ID": "0",
        "LUNCOPYTYPE": "1",
        "COPYPROGRESS": "100",
        "COPYSPEED": "2",
        "TYPE": 219,
        "COPYSTARTTIME": "1372209329"
    }]
}
"""

# A fake response of mappingview info response
FAKE_GET_MAPPING_VIEW_INFO_RESPONSE = """
{
    "error":{
        "code":0
    },
    "data":[{
        "WORKMODE":"255",
        "HEALTHSTATUS":"1",
        "NAME":"OpenStack_Mapping_View_1",
        "RUNNINGSTATUS":"27",
        "DESCRIPTION":"",
        "ENABLEINBANDCOMMAND":"true",
        "ID":"1",
        "INBANDLUNWWN":"",
        "TYPE":245
    },
    {
        "WORKMODE":"255",
        "HEALTHSTATUS":"1",
        "NAME":"YheUoRwbSX2BxN767nvLSw",
        "RUNNINGSTATUS":"27",
        "DESCRIPTION":"",
        "ENABLEINBANDCOMMAND":"true",
        "ID":"2",
        "INBANDLUNWWN": "",
        "TYPE": 245
    }]
}
"""

FAKE_GET_MAPPING_VIEW_RESPONSE = """
{
    "error":{
        "code":0
    },
    "data":[{
        "WORKMODE":"255",
        "HEALTHSTATUS":"1",
        "NAME":"mOWtSXnaQKi3hpB3tdFRIQ",
        "RUNNINGSTATUS":"27",
        "DESCRIPTION":"",
        "ENABLEINBANDCOMMAND":"true",
        "ID":"11",
        "INBANDLUNWWN":"",
        "TYPE": 245,
        "AVAILABLEHOSTLUNIDLIST": ""
    }]
}
"""

FAKE_GET_SPEC_MAPPING_VIEW_RESPONSE = """
{
    "error":{
        "code":0
    },
    "data":{
        "WORKMODE":"255",
        "HEALTHSTATUS":"1",
        "NAME":"mOWtSXnaQKi3hpB3tdFRIQ",
        "RUNNINGSTATUS":"27",
        "DESCRIPTION":"",
        "ENABLEINBANDCOMMAND":"true",
        "ID":"1",
        "INBANDLUNWWN":"",
        "TYPE":245,
        "AVAILABLEHOSTLUNIDLIST": "[1]"
    }
}
"""

FAKE_FC_INFO_RESPONSE = """
{
    "error":{
        "code":0
    },
    "data":[{
        "HEALTHSTATUS":"1",
        "NAME":"",
        "MULTIPATHTYPE":"1",
        "ISFREE":"true",
        "RUNNINGSTATUS":"27",
        "ID":"10000090fa0d6754",
        "OPERATIONSYSTEM":"255",
        "TYPE":223
    },
    {
        "HEALTHSTATUS":"1",
        "NAME":"",
        "MULTIPATHTYPE":"1",
        "ISFREE":"true",
        "RUNNINGSTATUS":"27",
        "ID":"10000090fa0d6755",
        "OPERATIONSYSTEM":"255",
        "TYPE":223
    }]
}
"""

FAKE_ISCSI_INITIATOR_RESPONSE = """
{
    "error":{
        "code":0
    },
    "data":[{
        "CHAPNAME":"mm-user",
        "HEALTHSTATUS":"1",
        "ID":"iqn.1993-08.org.debian:01:9073aba6c6f",
        "ISFREE":"true",
        "MULTIPATHTYPE":"1",
        "NAME":"",
        "OPERATIONSYSTEM":"255",
        "RUNNINGSTATUS":"28",
        "TYPE":222,
        "USECHAP":"true"
    },
    {
        "ISFREE":"true",
        "ID":"ini-1"
    },
    {
        "ISFREE":"false",
        "ID":"ini-2",
        "PARENTNAME":"Host2",
        "PARENTID":"2"
    }]
}
"""

FAKE_HOST_LINK_RESPONSE = """
{
    "error":{
        "code":0
    },
    "data":[{
        "PARENTTYPE":21,
        "TARGET_ID":"0000000000000000",
        "INITIATOR_NODE_WWN":"20000090fa0d6754",
        "INITIATOR_TYPE":"223",
        "RUNNINGSTATUS":"27",
        "PARENTNAME":"ubuntuc",
        "INITIATOR_ID":"10000090fa0d6754",
        "TARGET_PORT_WWN":"24000022a10a2a39",
        "HEALTHSTATUS":"1",
        "INITIATOR_PORT_WWN":"10000090fa0d6754",
        "ID":"010000090fa0d675-0000000000110400",
        "TARGET_NODE_WWN":"21000022a10a2a39",
        "PARENTID":"1",
        "CTRL_ID":"0",
        "TYPE":255,
        "TARGET_TYPE":"212"
    }]
}
"""

FAKE_PORT_GROUP_RESPONSE = """
{
    "error":{
        "code":0
    },
    "data":[{
        "ID":11,
        "NAME": "portgroup-test"
    }]
}
"""

FAKE_ERROR_INFO_RESPONSE = """
{
    "error":{
        "code":31755596
    }
}
"""

FAKE_ERROR_CONNECT_RESPONSE = """
{
    "error":{
        "code":-403
    }
}
"""

FAKE_ERROR_LUN_INFO_RESPONSE = """
{
    "error":{
        "code":0
    },
    "data":{
        "ID":"11",
        "IOCLASSID":"11",
        "NAME":"5mFHcBv4RkCcD+JyrWc0SA",
        "ALLOCTYPE": "0",
        "DATATRANSFERPOLICY": "0",
        "SMARTCACHEPARTITIONID": "0",
        "CACHEPARTITIONID": "0"
    }
}
"""
FAKE_GET_FC_INI_RESPONSE = """
{
    "error":{
        "code":0
    },
    "data":[{
        "ID":"10000090fa0d6754",
        "ISFREE":"true"
    }]
}
"""

FAKE_SYSTEM_VERSION_RESPONSE = """
{
    "error":{
        "code": 0
    },
    "data":{
        "PRODUCTVERSION": "V100R001C10",
        "wwn": "21003400a30d844d"
    }
}
"""

FAKE_GET_LUN_MIGRATION_RESPONSE = """
{
    "data":[{"ENDTIME":"1436816174",
             "ID":"9",
             "PARENTID":"11",
             "PARENTNAME":"xmRBHMlVRruql5vwthpPXQ",
             "PROCESS":"-1",
             "RUNNINGSTATUS":"76",
             "SPEED":"2",
             "STARTTIME":"1436816111",
             "TARGETLUNID":"1",
             "TARGETLUNNAME":"4924891454902893639",
             "TYPE":253,
             "WORKMODE":"0"
             }],
    "error":{"code":0,
             "description":"0"}
}
"""

FAKE_HYPERMETRODOMAIN_RESPONSE = """
{
    "error":{
        "code": 0
    },
    "data":[{
        "PRODUCTVERSION": "V100R001C10",
        "ID": "11",
        "NAME": "hypermetro_test",
        "RUNNINGSTATUS": "1",
        "HEALTHSTATUS": "0"
    }]
}
"""

FAKE_HYPERMETRO_RESPONSE = """
{
    "error":{
        "code": 0
    },
    "data":{
        "PRODUCTVERSION": "V100R001C10",
        "ID": "11",
        "NAME": "hypermetro_test",
        "RUNNINGSTATUS": "1",
        "HEALTHSTATUS": "1"
    }
}
"""

FAKE_QOS_INFO_RESPONSE = """
{
    "error":{
        "code": 0
    },
    "data":{
        "ID": "11"
    }
}
"""

FAKE_GET_FC_PORT_RESPONSE = """
{
    "error":{
        "code":0
    },
    "data":[{
        "RUNNINGSTATUS":"10",
        "WWN":"2000643e8c4c5f66",
        "PARENTID":"0A.1",
        "ID": "1114368",
        "RUNSPEED": "16000"
    },
    {
        "RUNNINGSTATUS":"10",
        "WWN":"2000643e8c4c5f67",
        "PARENTID":"0A.1",
        "ID": "1114369",
        "RUNSPEED": "16000"
    }]
}
"""

FAKE_SMARTCACHEPARTITION_RESPONSE = """
{
    "error":{
        "code":0
    },
    "data":{
        "ID":"11",
        "NAME":"cache-name"
    }
}
"""

FAKE_CONNECT_FC_RESPONSE = {
    "driver_volume_type": 'fibre_channel',
    "data": {
        "target_wwn": ["10000090fa0d6754"],
        "target_lun": "1",
        "volume_id": ID
    }
}

FAKE_METRO_INFO_RESPONSE = {
    "PRODUCTVERSION": "V100R001C10",
    "ID": "11",
    "NAME": "hypermetro_test",
    "RUNNINGSTATUS": "42",
    "HEALTHSTATUS": "0"
}

FAKE_METRO_INFO_NEW_RESPONSE = """{
    "error": {
        "code": 0
    },
    "data": {
        "PRODUCTVERSION": "V100R001C10",
        "ID": "11",
        "NAME": "hypermetro_test",
        "RUNNINGSTATUS": "1",
        "HEALTHSTATUS": "1"
    }
}
"""

FAKE_CREATE_METROROUP_RESPONSE = """
{
    "data": {
        "DESCRIPTION": "",
        "DOMAINID": "643e8c4c5f670100",
        "DOMAINNAME": "hypermetro-domain",
        "HEALTHSTATUS": "1",
        "ID": "3400a30d844d8002",
        "ISEMPTY": "true",
        "NAME": "6F7kdHZcQJ2zbzxHmBl4FQ",
        "PRIORITYSTATIONTYPE": "0",
        "RECOVERYPOLICY": "1",
        "RESOURCETYPE": "11",
        "RUNNINGSTATUS": "41",
        "SPEED": "2",
        "SYNCDIRECTION": "1",
        "TYPE": 15364
    },
    "error": {
        "code": 0,
        "description": "0"
    }
}
"""

FAKE_GET_METROROUP_RESPONSE = {
    "data": [{
        "DESCRIPTION": "",
        "DOMAINID": "643e8c4c5f670100",
        "DOMAINNAME": "hypermetro-domain",
        "HEALTHSTATUS": "1",
        "ID": "11",
        "ISEMPTY": "true",
        "NAME": huawei_utils.encode_name(ID),
        "PRIORITYSTATIONTYPE": "0",
        "RECOVERYPOLICY": "1",
        "RESOURCETYPE": "11",
        "RUNNINGSTATUS": "41",
        "SPEED": "2",
        "SYNCDIRECTION": "1",
        "TYPE": 15364
    }],
    "error": {
        "code": 0,
        "description": "0"
    },
}


FAKE_GET_METROROUP_ID_RESPONSE = """
{
    "data": {
        "DESCRIPTION": "",
        "DOMAINID": "643e8c4c5f670100",
        "DOMAINNAME": "hypermetro-domain",
        "HEALTHSTATUS": "1",
        "ID": "11",
        "ISEMPTY": "false",
        "NAME": "IexzQZJWSXuX2e9I7c8GNQ",
        "PRIORITYSTATIONTYPE": "0",
        "RECOVERYPOLICY": "1",
        "RESOURCETYPE": "11",
        "RUNNINGSTATUS": "1",
        "SPEED": "2",
        "SYNCDIRECTION": "1",
        "TYPE": 15364
    },
    "error": {
        "code": 0,
        "description": "0"
    }
}
"""

# mock login info map
MAP_COMMAND_TO_FAKE_RESPONSE = {}

MAP_COMMAND_TO_FAKE_RESPONSE['/xx/sessions/POST'] = (
    FAKE_GET_LOGIN_STORAGE_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/sessions/DELETE'] = (
    FAKE_LOGIN_OUT_STORAGE_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/LUN_MIGRATION/POST'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/LUN_MIGRATION?range=[0-256]/GET'] = (
    FAKE_GET_LUN_MIGRATION_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/LUN_MIGRATION/11/DELETE'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

# mock storage info map
MAP_COMMAND_TO_FAKE_RESPONSE['/storagepool/GET'] = (
    FAKE_STORAGE_POOL_RESPONSE)

# mock lun info map
MAP_COMMAND_TO_FAKE_RESPONSE['/lun/POST'] = (
    FAKE_LUN_INFO_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/lun/11/GET'] = (
    FAKE_LUN_GET_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/lun/1/GET'] = (
    FAKE_LUN_GET_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/lun/11/DELETE'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/lun/1/DELETE'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/lun/1/PUT'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/lun/11/PUT'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/lun?filter=NAME::%s/GET' % ENCODE_NAME] = (
    json.dumps(FAKE_QUERY_ALL_LUN_RESPONSE))

MAP_COMMAND_TO_FAKE_RESPONSE['/lun?filter=NAME::%s/GET' % OLD_ENCODE_NAME] = (
    json.dumps(FAKE_QUERY_ALL_LUN_RESPONSE))

MAP_COMMAND_TO_FAKE_RESPONSE['/lun/associate?TYPE=11&ASSOCIATEOBJTYPE=256'
                             '&ASSOCIATEOBJID=11/GET'] = (
    FAKE_LUN_ASSOCIATE_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/lun/associate?TYPE=11&ASSOCIATEOBJTYPE=256'
                             '&ASSOCIATEOBJID=12/GET'] = (
    FAKE_LUN_ASSOCIATE_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/lun/associate?ID=1&TYPE=11&ASSOCIATEOBJTYPE=21'
                             '&ASSOCIATEOBJID=0/GET'] = (
    FAKE_LUN_ASSOCIATE_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/lun/associate?TYPE=11&ASSOCIATEOBJTYPE=21'
                             '&ASSOCIATEOBJID=1/GET'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/lun/associate/cachepartition?ID=1'
                             '&ASSOCIATEOBJTYPE=11&ASSOCIATEOBJID=11'
                             '/DELETE'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/snapshot/associate?TYPE=27&ASSOCIATEOBJTYPE=21'
                             '&ASSOCIATEOBJID=1/GET'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/snapshot/associate?TYPE=27&ASSOCIATEOBJTYPE=256'
                             '&ASSOCIATEOBJID=11/GET'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/lungroup?range=[0-8191]/GET'] = (
    FAKE_QUERY_LUN_GROUP_INFO_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/lungroup/POST'] = (
    FAKE_QUERY_LUN_GROUP_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/lungroup/associate/POST'] = (
    FAKE_QUERY_LUN_GROUP_ASSOCIAT_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/LUNGroup/11/DELETE'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/lungroup/associate?ID=11&ASSOCIATEOBJTYPE=11'
                             '&ASSOCIATEOBJID=1/DELETE'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/lungroup/associate?TYPE=256&ASSOCIATEOBJTYPE=11'
                             '&ASSOCIATEOBJID=11/GET'] = (
    FAKE_LUN_ASSOCIATE_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/lungroup/associate?TYPE=256&ASSOCIATEOBJTYPE=11'
                             '&ASSOCIATEOBJID=1/GET'] = (
    FAKE_LUN_ASSOCIATE_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/lungroup/associate?ID=11&ASSOCIATEOBJTYPE=11'
                             '&ASSOCIATEOBJID=11/DELETE'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/lungroup/associate?ID=11&ASSOCIATEOBJTYPE=27'
                             '&ASSOCIATEOBJID=11/DELETE'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/lun/count?TYPE=11&ASSOCIATEOBJTYPE=256'
                             '&ASSOCIATEOBJID=11/GET'] = (
    FAKE_LUN_COUNT_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/snapshot/count?TYPE=27&ASSOCIATEOBJTYPE=256'
                             '&ASSOCIATEOBJID=1/GET'] = (
    FAKE_SNAPSHOT_COUNT_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/snapshot/count?TYPE=27&ASSOCIATEOBJTYPE=256'
                             '&ASSOCIATEOBJID=11/GET'] = (
    FAKE_SNAPSHOT_COUNT_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/lungroup/associate?TYPE=256&ASSOCIATEOBJTYPE=27'
                             '&ASSOCIATEOBJID=11/GET'] = (
    FAKE_LUN_ASSOCIATE_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/lun/expand/PUT'] = (
    FAKE_LUN_INFO_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/lungroup/associate?ID=12&ASSOCIATEOBJTYPE=11'
                             '&ASSOCIATEOBJID=12/DELETE'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

# mock snapshot info map
MAP_COMMAND_TO_FAKE_RESPONSE['/snapshot/POST'] = (
    FAKE_CREATE_SNAPSHOT_INFO_RESPONSE)

# mock snapshot info map
MAP_COMMAND_TO_FAKE_RESPONSE['/snapshot/11/GET'] = (
    FAKE_GET_SNAPSHOT_INFO_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/snapshot/activate/POST'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/snapshot/stop/PUT'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/snapshot/11/DELETE'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/snapshot?filter=NAME::%s/GET' % ENCODE_NAME] = (
    json.dumps(FAKE_SNAPSHOT_LIST_INFO_RESPONSE))

MAP_COMMAND_TO_FAKE_RESPONSE['/snapshot?filter=NAME::%s/GET'
                             % OLD_ENCODE_NAME] = (
    json.dumps(FAKE_SNAPSHOT_LIST_INFO_RESPONSE))

# mock QoS info map
MAP_COMMAND_TO_FAKE_RESPONSE['/ioclass/11/GET'] = (
    FAKE_LUN_GET_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/ioclass/11/DELETE'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/ioclass/11/PUT'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/ioclass/active/11/PUT'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/ioclass/POST'] = (
    FAKE_QOS_INFO_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/ioclass/count/GET'] = (
    FAKE_COMMON_FAIL_RESPONSE)

# mock iscsi info map
MAP_COMMAND_TO_FAKE_RESPONSE['/iscsi_tgt_port/GET'] = (
    FAKE_GET_ISCSI_INFO_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/eth_port/GET'] = (
    FAKE_GET_ETH_INFO_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/eth_port/associate?TYPE=213&ASSOCIATEOBJTYPE'
                             '=257&ASSOCIATEOBJID=11/GET'] = (
    FAKE_GET_ETH_ASSOCIATE_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/iscsidevicename/GET'] = (
    FAKE_GET_ISCSI_DEVICE_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/iscsi_initiator?range=[0-256]/GET'] = (
    FAKE_ISCSI_INITIATOR_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/iscsi_initiator/GET'] = (
    FAKE_ISCSI_INITIATOR_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/iscsi_initiator/POST'] = (
    FAKE_ISCSI_INITIATOR_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/iscsi_initiator/PUT'] = (
    FAKE_ISCSI_INITIATOR_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/iscsi_initiator?PARENTTYPE=21&PARENTID'
                             '=1/GET'] = (
    FAKE_ISCSI_INITIATOR_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/iscsi_initiator/remove_iscsi_from_host/PUT'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/iscsi_initiator/'
                             'iqn.1993-08.debian:01:ec2bff7ac3a3/PUT'] = (
    FAKE_ISCSI_INITIATOR_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/host?filter=NAME::%s/GET' % ENCODE_HOST_NAME
                             ] = FAKE_PATCH_GET_HOST_RESPONSE

MAP_COMMAND_TO_FAKE_RESPONSE['/host?filter=NAME::%s/GET' % OLD_ENCODE_HOST_NAME
                             ] = FAKE_PATCH_GET_HOST_RESPONSE

MAP_COMMAND_TO_FAKE_RESPONSE['/host/1/DELETE'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/host/1/GET'] = (
    FAKE_GET_HOST_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/host/POST'] = (
    FAKE_CREATE_HOST_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/hostgroup?range=[0-8191]/GET'] = (
    FAKE_GET_ALL_HOST_GROUP_INFO_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/hostgroup/GET'] = (
    FAKE_GET_HOST_GROUP_INFO_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/host/associate?TYPE=14&ID=0'
                             '&ASSOCIATEOBJTYPE=21&ASSOCIATEOBJID=1'
                             '/DELETE'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/host/associate?TYPE=14&ID=0'
                             '&ASSOCIATEOBJID=0/GET'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/host/associate?TYPE=21&'
                             'ASSOCIATEOBJTYPE=14&ASSOCIATEOBJID=0/GET'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/hostgroup/0/DELETE'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/host/associate?TYPE=21&'
                             'ASSOCIATEOBJTYPE=14&ASSOCIATEOBJID=0/GET'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)


MAP_COMMAND_TO_FAKE_RESPONSE['/hostgroup/associate/POST'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

# mock copy info map
MAP_COMMAND_TO_FAKE_RESPONSE['/luncopy/POST'] = (
    FAKE_GET_LUN_COPY_INFO_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/LUNCOPY?range=[0-1023]/GET'] = (
    FAKE_GET_LUN_COPY_LIST_INFO_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/LUNCOPY/start/PUT'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/LUNCOPY/0/DELETE'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

# mock mapping view info map
MAP_COMMAND_TO_FAKE_RESPONSE['/mappingview?range=[0-8191]/GET'] = (
    FAKE_GET_MAPPING_VIEW_INFO_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/mappingview/POST'] = (
    FAKE_GET_MAPPING_VIEW_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/mappingview/PUT'] = (
    FAKE_GET_MAPPING_VIEW_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/MAPPINGVIEW/1/GET'] = (
    FAKE_GET_SPEC_MAPPING_VIEW_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/mappingview/1/DELETE'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/mappingview/REMOVE_ASSOCIATE/PUT'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/mappingview/associate/lungroup?TYPE=256&'
                             'ASSOCIATEOBJTYPE=245&ASSOCIATEOBJID=1/GET'] = (
    FAKE_GET_MAPPING_VIEW_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/mappingview/associate?TYPE=245&'
                             'ASSOCIATEOBJTYPE=14&ASSOCIATEOBJID=0/GET'] = (
    FAKE_GET_MAPPING_VIEW_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/mappingview/associate?TYPE=245&'
                             'ASSOCIATEOBJTYPE=256&ASSOCIATEOBJID=11/GET'] = (
    FAKE_GET_MAPPING_VIEW_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/mappingview/associate?TYPE=245&'
                             'ASSOCIATEOBJTYPE=257&ASSOCIATEOBJID=0/GET'] = (
    FAKE_GET_MAPPING_VIEW_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/mappingview/associate?TYPE=245&'
                             'ASSOCIATEOBJTYPE=257&ASSOCIATEOBJID=11/GET'] = (
    FAKE_GET_MAPPING_VIEW_RESPONSE)

FAKE_GET_ENGINES_RESPONSE = """
{
    "error":{
        "code": 0
    },
    "data":[{
        "NODELIST": "[]",
        "ID": "0"
    }]
}
"""

MAP_COMMAND_TO_FAKE_RESPONSE['/storageengine/GET'] = (
    FAKE_GET_ENGINES_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/portgroup/associate?ASSOCIATEOBJTYPE=245&'
                             'ASSOCIATEOBJID=1&range=[0-8191]/GET'] = (
    FAKE_GET_MAPPING_VIEW_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/MAPPINGVIEW/CREATE_ASSOCIATE/PUT'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

# mock FC info map
MAP_COMMAND_TO_FAKE_RESPONSE['/fc_initiator?ISFREE=true&'
                             'range=[0-8191]/GET'] = (
    FAKE_FC_INFO_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/MAPPINGVIEW/CREATE_ASSOCIATE/PUT'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

# mock FC info map
MAP_COMMAND_TO_FAKE_RESPONSE['/fc_initiator?ISFREE=true&'
                             'range=[0-8191]/GET'] = (
    FAKE_FC_INFO_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/fc_initiator/10000090fa0d6754/GET'] = (
    FAKE_FC_INFO_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/fc_initiator/10000090fa0d6754/PUT'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/host_link?INITIATOR_TYPE=223'
                             '&INITIATOR_PORT_WWN=10000090fa0d6754/GET'] = (
    FAKE_HOST_LINK_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/portgroup?range=[0-8191]&TYPE=257/GET'] = (
    FAKE_PORT_GROUP_RESPONSE)

# mock system info map
MAP_COMMAND_TO_FAKE_RESPONSE['/system//GET'] = (
    FAKE_SYSTEM_VERSION_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/fc_initiator?range=[0-256]/GET'] = (
    FAKE_GET_FC_INI_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/fc_port/GET'] = (
    FAKE_GET_FC_PORT_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/fc_initiator/GET'] = (
    FAKE_GET_FC_PORT_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['fc_initiator?range=[0-256]/GET'] = (
    FAKE_GET_FC_PORT_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/fc_initiator?PARENTTYPE=21&PARENTID=1/GET'] = (
    FAKE_GET_FC_PORT_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/lun/associate/cachepartition/POST'] = (
    FAKE_SYSTEM_VERSION_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/fc_initiator?range=[0-256]&PARENTID=1/GET'] = (
    FAKE_GET_FC_PORT_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/fc_initiator?PARENTTYPE=21&PARENTID=1/GET'] = (
    FAKE_GET_FC_PORT_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/fc_initiator/count/GET'] = '''
    {"data":{"COUNT":"2"},"error":{"code":0}}'''

MAP_COMMAND_TO_FAKE_RESPONSE['/fc_initiator?range=[0-100]/GET'] = (
    FAKE_FC_INFO_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/SMARTCACHEPARTITION/0/GET'] = (
    FAKE_SMARTCACHEPARTITION_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/SMARTCACHEPARTITION/REMOVE_ASSOCIATE/PUT'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/SMARTCACHEPARTITION/count/GET'] = (
    FAKE_COMMON_FAIL_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/cachepartition/0/GET'] = (
    FAKE_SMARTCACHEPARTITION_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/HyperMetroDomain?range=[0-32]/GET'] = (
    FAKE_HYPERMETRODOMAIN_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/HyperMetroPair/POST'] = (
    FAKE_HYPERMETRO_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/HyperMetroPair/3400a30d844d0007/GET'] = (
    FAKE_METRO_INFO_NEW_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/HyperMetroPair/disable_hcpair/PUT'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/hyperMetro/associate/pair/POST'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/hyperMetro/associate/pair/DELETE'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/HyperMetroPair/11/DELETE'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/HyperMetroPair/11/GET'] = (
    FAKE_HYPERMETRO_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/HyperMetroPair?range=[0-4095]/GET'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/HyperMetroPair/synchronize_hcpair/PUT'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/splitmirror?range=[0-8191]/GET'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/splitmirror/count/GET'] = (
    FAKE_COMMON_FAIL_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/smartcachepool/count/GET'] = (
    FAKE_COMMON_FAIL_RESPONSE)

FAKE_GET_PORTG_BY_VIEW = """
{
    "data": [{
        "DESCRIPTION": "Please do NOT modify this. Engine ID: 0",
        "ID": "0",
        "NAME": "OpenStack_PortGroup_1",
        "TYPE": 257
    }],
    "error": {
        "code": 0
    }
}
"""

MAP_COMMAND_TO_FAKE_RESPONSE['/portgroup/associate/mappingview?TYPE=257&AS'
                             'SOCIATEOBJTYPE=245&ASSOCIATEOBJID=1/GET'] = (
    FAKE_GET_PORTG_BY_VIEW)

FAKE_GET_PORT_BY_PORTG = """
{
    "data":[{
        "CONFSPEED":"0","FCCONFMODE":"3",
        "FCRUNMODE":"0","HEALTHSTATUS":"1","ID":"2000643e8c4c5f66",
        "MAXSUPPORTSPEED":"16000","NAME":"P0","PARENTID":"0B.1",
        "PARENTTYPE":209,"RUNNINGSTATUS":"10","RUNSPEED":"8000",
        "WWN":"2000643e8c4c5f66"
    }],
    "error":{
        "code":0,"description":"0"
    }
}
"""

MAP_COMMAND_TO_FAKE_RESPONSE['/fc_port/associate/portgroup?TYPE=212&ASSOCI'
                             'ATEOBJTYPE=257&ASSOCIATEOBJID=0/GET'] = (
    FAKE_GET_PORT_BY_PORTG)

FAKE_GET_PORTG = """
{
    "data": {
        "TYPE": 257,
        "NAME": "OpenStack_PortGroup_1",
        "DESCRIPTION": "Please DO NOT change thefollowing message: 0",
        "ID": "0"
    },
    "error": {
        "code": 0,
        "description": "0"
    }
}
"""

MAP_COMMAND_TO_FAKE_RESPONSE['/portgroup/0/GET'] = FAKE_GET_PORTG

MAP_COMMAND_TO_FAKE_RESPONSE['/portgroup/0/PUT'] = FAKE_GET_PORTG

MAP_COMMAND_TO_FAKE_RESPONSE['/port/associate/portgroup/POST'] = (
    FAKE_GET_PORT_BY_PORTG)

MAP_COMMAND_TO_FAKE_RESPONSE['/port/associate/portgroup?ID=0&TYPE=257&ASSOCIA'
                             'TEOBJTYPE=212&ASSOCIATEOBJID=2000643e8c4c5f66/DE'
                             'LETE'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

FAKE_CREATE_PORTG = """
{
    "data": {
        "DESCRIPTION": "Please DO NOT change the following message: 0",
        "ID": "0",
        "NAME": "OpenStack_PortGroup_1",
        "TYPE": 257
    },
    "error": {
        "code": 0,
        "description": "0"
    }
}
"""

MAP_COMMAND_TO_FAKE_RESPONSE['/PortGroup/POST'] = FAKE_CREATE_PORTG

MAP_COMMAND_TO_FAKE_RESPONSE['/PortGroup/1/DELETE'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

FAKE_GET_PORTG_FROM_PORT = """
{
    "data": [{
        "TYPE": 257,
        "NAME": "OpenStack_PortGroup_1",
        "DESCRIPTION": "PleaseDONOTchangethefollowingmessage: 0",
        "ID": "0"
    }],
    "error": {
        "code": 0,
        "description": "0"
    }
}
"""

MAP_COMMAND_TO_FAKE_RESPONSE['/portgroup/associate/fc_port?TYPE=257&ASSOCIA'
                             'TEOBJTYPE=212&ASSOCIATEOBJID=1114368/GET'] = (
    FAKE_GET_PORTG_FROM_PORT)

FAKE_GET_VIEW_BY_PORTG = """
{
    "data": [{
        "ASSOCIATEOBJID": "0",
        "COUNT": "0",
        "ASSOCIATEOBJTYPE": "0",
        "INBANDLUNWWN": "",
        "FORFILESYSTEM": "false",
        "ID": "2",
        "ENABLEINBANDCOMMAND": "false",
        "NAME": "OpenStack_Mapping_View_1",
        "WORKMODE": "0",
        "TYPE": 245,
        "HOSTLUNID": "0",
        "DESCRIPTION": ""
    }],
    "error": {
        "code": 0,
        "description": "0"
    }
}
"""

MAP_COMMAND_TO_FAKE_RESPONSE['/mappingview/associate/portgroup?TYPE=245&ASS'
                             'OCIATEOBJTYPE=257&ASSOCIATEOBJID=0/GET'] = (
    FAKE_GET_VIEW_BY_PORTG)

FAKE_GET_LUNG_BY_VIEW = """
{
    "data": [{
        "TYPE": 256,
        "NAME": "OpenStack_LunGroup_1",
        "DESCRIPTION": "OpenStack_LunGroup_1",
        "ID": "1"
    }],
    "error": {
        "code": 0,
        "description": "0"
    }
}
"""

MAP_COMMAND_TO_FAKE_RESPONSE['/lungroup/associate/mappingview?TYPE=256&ASSO'
                             'CIATEOBJTYPE=245&ASSOCIATEOBJID=2/GET'] = (
    FAKE_GET_LUNG_BY_VIEW)

FAKE_LUN_COUNT_RESPONSE_1 = """
{
    "data":{
        "COUNT":"2"
    },
    "error":{
        "code":0,
        "description":"0"
    }
}
"""

MAP_COMMAND_TO_FAKE_RESPONSE['/lun/count?TYPE=11&ASSOCIATEOB'
                             'JTYPE=256&ASSOCIATEOBJID=1/GET'] = (
    FAKE_LUN_COUNT_RESPONSE_1)

FAKE_PORTS_IN_PG_RESPONSE = """
{
    "data": [{
        "ID": "1114114",
        "WWN": "2002643e8c4c5f66"
    },
    {
        "ID": "1114113",
        "WWN": "2001643e8c4c5f66"
    }],
    "error": {
        "code": 0,
        "description": "0"
    }
}
"""

MAP_COMMAND_TO_FAKE_RESPONSE['/fc_port/associate?TYPE=213&ASSOCIATEOBJTYPE='
                             '257&ASSOCIATEOBJID=0/GET'] = (
    FAKE_PORTS_IN_PG_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/HyperMetro_ConsistentGroup/POST'] = (
    FAKE_CREATE_METROROUP_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE["/HyperMetro_ConsistentGroup?type"
                             "='15364'/GET"] = (
    json.dumps(FAKE_GET_METROROUP_RESPONSE))

MAP_COMMAND_TO_FAKE_RESPONSE["/HyperMetro_ConsistentGroup/11/GET"] = (
    FAKE_GET_METROROUP_ID_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE["/HyperMetro_ConsistentGroup/11/DELETE"] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE["/HyperMetro_ConsistentGroup/stop/PUT"] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE["/HyperMetro_ConsistentGroup/sync/PUT"] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

FAKE_GET_REMOTEDEV_RESPONSE = """
{
    "data":[{
        "ARRAYTYPE":"1",
        "HEALTHSTATUS":"1",
        "ID":"0",
        "NAME":"Huawei.Storage",
        "RUNNINGSTATUS":"1",
        "WWN":"21003400a30d844d"
    }],
    "error":{
        "code":0,
        "description":"0"
    }
}
"""

MAP_COMMAND_TO_FAKE_RESPONSE['/remote_device/GET'] = (
    FAKE_GET_REMOTEDEV_RESPONSE)

FAKE_CREATE_PAIR_RESPONSE = """
{
    "data":{
        "ID":"%s"
    },
    "error":{
        "code":0,
        "description":"0"
    }
}
""" % TEST_PAIR_ID
MAP_COMMAND_TO_FAKE_RESPONSE['/REPLICATIONPAIR/POST'] = (
    FAKE_CREATE_PAIR_RESPONSE)

FAKE_DELETE_PAIR_RESPONSE = """
{
    "data":{},
    "error":{
        "code":0,
        "description":"0"
    }
}
"""
MAP_COMMAND_TO_FAKE_RESPONSE['/REPLICATIONPAIR/%s/DELETE' % TEST_PAIR_ID] = (
    FAKE_DELETE_PAIR_RESPONSE)

FAKE_SET_PAIR_ACCESS_RESPONSE = """
{
    "data":{},
    "error":{
        "code":0,
        "description":"0"
    }
}
"""
MAP_COMMAND_TO_FAKE_RESPONSE['/REPLICATIONPAIR/%s/PUT' % TEST_PAIR_ID] = (
    FAKE_SET_PAIR_ACCESS_RESPONSE)

FAKE_GET_PAIR_NORMAL_RESPONSE = """
{
    "data":{
        "REPLICATIONMODEL": "1",
        "RUNNINGSTATUS": "1",
        "SECRESACCESS": "2",
        "HEALTHSTATUS": "1",
        "ISPRIMARY": "true"
    },
    "error":{
        "code":0,
        "description":"0"
    }
}
"""

FAKE_GET_PAIR_SPLIT_RESPONSE = """
{
    "data":{
        "REPLICATIONMODEL": "1",
        "RUNNINGSTATUS": "26",
        "SECRESACCESS": "2",
        "ISPRIMARY": "true"
    },
    "error":{
        "code":0,
        "description":"0"
    }
}
"""

FAKE_GET_PAIR_SYNC_RESPONSE = """
{
    "data":{
        "REPLICATIONMODEL": "1",
        "RUNNINGSTATUS": "23",
        "SECRESACCESS": "2"
    },
    "error":{
        "code":0,
        "description":"0"
    }
}
"""
MAP_COMMAND_TO_FAKE_RESPONSE['/REPLICATIONPAIR/%s/GET' % TEST_PAIR_ID] = (
    FAKE_GET_PAIR_NORMAL_RESPONSE)

FAKE_SYNC_PAIR_RESPONSE = """
{
    "data":{},
    "error":{
        "code":0,
        "description":"0"
    }
}
"""
MAP_COMMAND_TO_FAKE_RESPONSE['/REPLICATIONPAIR/sync/PUT'] = (
    FAKE_SYNC_PAIR_RESPONSE)

FAKE_SPLIT_PAIR_RESPONSE = """
{
    "data":{},
    "error":{
        "code":0,
        "description":"0"
    }
}
"""
MAP_COMMAND_TO_FAKE_RESPONSE['/REPLICATIONPAIR/split/PUT'] = (
    FAKE_SPLIT_PAIR_RESPONSE)

FAKE_SWITCH_PAIR_RESPONSE = """
{
    "data":{},
    "error":{
        "code":0,
        "description":"0"
    }
}
"""
MAP_COMMAND_TO_FAKE_RESPONSE['/REPLICATIONPAIR/switch/PUT'] = (
    FAKE_SWITCH_PAIR_RESPONSE)

FAKE_PORTS_IN_PG_RESPONSE = """
{
    "data": [{
        "ID": "1114114",
        "WWN": "2002643e8c4c5f66"
    },
    {
        "ID": "1114113",
        "WWN": "2001643e8c4c5f66"
    }],
    "error": {
        "code": 0,
        "description": "0"
    }
}
"""

MAP_COMMAND_TO_FAKE_RESPONSE['/fc_port/associate?TYPE=213&ASSOCIATEOBJTYPE='
                             '257&ASSOCIATEOBJID=0/GET'] = (
    FAKE_PORTS_IN_PG_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/portgroup/associate/fc_port?TYPE=257&ASSOCIA'
                             'TEOBJTYPE=212&ASSOCIATEOBJID=1114369/GET'] = (
    FAKE_PORTS_IN_PG_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/mappingview/associate/portgroup?TYPE=245&ASSOC'
                             'IATEOBJTYPE=257&ASSOCIATEOBJID=1114114/GET'] = (
    FAKE_SWITCH_PAIR_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/mappingview/associate/portgroup?TYPE=245&ASSOC'
                             'IATEOBJTYPE=257&ASSOCIATEOBJID=1114113/GET'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)


REPLICA_BACKEND_ID = 'huawei-replica-1'


class FakeHuaweiConf(huawei_conf.HuaweiConf):
    def __init__(self, conf, protocol):
        self.conf = conf
        self.protocol = protocol

    def safe_get(self, key):
        try:
            return getattr(self.conf, key)
        except Exception:
            return

    def update_config_value(self):
        setattr(self.conf, 'volume_backend_name', 'huawei_storage')
        setattr(self.conf, 'san_address',
                ['http://192.0.2.69:8082/deviceManager/rest/'])
        setattr(self.conf, 'san_user', 'admin')
        setattr(self.conf, 'san_password', 'Admin@storage')
        setattr(self.conf, 'san_product', 'V3')
        setattr(self.conf, 'san_protocol', self.protocol)
        setattr(self.conf, 'lun_type', constants.THICK_LUNTYPE)
        setattr(self.conf, 'lun_ready_wait_interval', 2)
        setattr(self.conf, 'lun_copy_wait_interval', 2)
        setattr(self.conf, 'lun_timeout', 43200)
        setattr(self.conf, 'lun_write_type', '1')
        setattr(self.conf, 'lun_mirror_switch', '1')
        setattr(self.conf, 'lun_prefetch_type', '1')
        setattr(self.conf, 'lun_prefetch_value', '0')
        setattr(self.conf, 'lun_policy', '0')
        setattr(self.conf, 'lun_read_cache_policy', '2')
        setattr(self.conf, 'lun_write_cache_policy', '5')
        setattr(self.conf, 'storage_pools', ['OpenStack_Pool'])
        setattr(self.conf, 'iscsi_default_target_ip', ['192.0.2.68'])
        setattr(self.conf, 'metro_san_address',
                ['https://192.0.2.240:8088/deviceManager/rest/'])
        setattr(self.conf, 'metro_storage_pools', 'OpenStack_Pool')
        setattr(self.conf, 'metro_san_user', 'admin')
        setattr(self.conf, 'metro_san_password', 'Admin@storage1')
        setattr(self.conf, 'metro_domain_name', 'hypermetro_test')

        iscsi_info = {
            'default_target_ips': '192.0.2.2',
            'initiators': {
                'iqn.1993-08.debian:01:ec2bff7ac3a3': {
                    'Name': 'iqn.1993-08.debian:01:ec2bff7ac3a3',
                    'CHAPinfo': 'mm-user;mm-user@storage',
                    'ALUA': '1',
                    'TargetPortGroup': 'portgroup-test',
                }
            }
        }
        setattr(self.conf, 'iscsi_info', iscsi_info)

        rmt_iscsi_info = {'Name': 'iqn.1993-08.debian:01:ec2bff7acxxx',
                          'TargetIP': '1.1.1.1',
                          'CHAPinfo': 'mm-user;mm-user@storage',
                          'ALUA': '1',
                          'TargetPortGroup': 'portgroup-test'}

        target = {'backend_id': REPLICA_BACKEND_ID,
                  'storage_pool': 'OpenStack_Pool',
                  'san_address':
                      'https://192.0.2.69:8088/deviceManager/rest/',
                  'san_user': 'admin',
                  'san_password': 'Admin@storage1',
                  'iscsi_info': rmt_iscsi_info}
        setattr(self.conf, 'replication', target)

        setattr(self.conf, 'safe_get', self.safe_get)


class FakeClient(rest_client.RestClient):

    def __init__(self, configuration):
        san_address = configuration.san_address
        san_user = configuration.san_user
        san_password = configuration.san_password
        rest_client.RestClient.__init__(self, configuration,
                                        san_address,
                                        san_user,
                                        san_password)
        self.test_fail = False
        self.test_multi_url_flag = False
        self.cache_not_exist = False
        self.partition_not_exist = False

    def _get_snapshotid_by_name(self, snapshot_name):
        return "11"

    def _check_snapshot_exist(self, snapshot_id):
        return True

    def get_partition_id_by_name(self, name):
        if self.partition_not_exist:
            return None
        return "11"

    def get_cache_id_by_name(self, name):
        if self.cache_not_exist:
            return None
        return "11"

    def add_lun_to_cache(self, lunid, cache_id):
        pass

    def do_call(self, url, data, method, calltimeout=4,
                log_filter_flag=False):
        url = url.replace('http://192.0.2.69:8082/deviceManager/rest', '')
        command = url.replace('/210235G7J20000000000/', '')
        data = FAKE_COMMON_SUCCESS_RESPONSE

        if method:
            command = command + "/" + method

        for item in MAP_COMMAND_TO_FAKE_RESPONSE:
            if command == item:
                data = MAP_COMMAND_TO_FAKE_RESPONSE[item]
                if self.test_fail:
                    data = FAKE_ERROR_INFO_RESPONSE
                    if command == 'lun/11/GET':
                        data = FAKE_ERROR_LUN_INFO_RESPONSE

                    self.test_fail = False

        if self.test_multi_url_flag:
            data = FAKE_ERROR_CONNECT_RESPONSE
            self.test_multi_url_flag = False

        return json.loads(data)


class FakeReplicaPairManager(replication.ReplicaPairManager):
    def _init_rmt_client(self):
        self.rmt_client = FakeClient(self.conf)


class FakeISCSIStorage(huawei_driver.HuaweiISCSIDriver):
    """Fake Huawei Storage, Rewrite some methods of HuaweiISCSIDriver."""

    def __init__(self, configuration):
        self.configuration = configuration
        self.huawei_conf = FakeHuaweiConf(self.configuration, 'iSCSI')
        self.active_backend_id = None
        self.replica = None
        self.support_func = None

    def do_setup(self):
        self.metro_flag = True
        self.huawei_conf.update_config_value()
        self.get_local_and_remote_dev_conf()

        self.client = FakeClient(configuration=self.configuration)
        self.rmt_client = FakeClient(configuration=self.configuration)
        self.replica_client = FakeClient(configuration=self.configuration)
        self.metro = hypermetro.HuaweiHyperMetro(self.client,
                                                 self.rmt_client,
                                                 self.configuration)
        self.replica = FakeReplicaPairManager(self.client,
                                              self.replica_client,
                                              self.configuration)


class FakeFCStorage(huawei_driver.HuaweiFCDriver):
    """Fake Huawei Storage, Rewrite some methods of HuaweiISCSIDriver."""

    def __init__(self, configuration):
        self.configuration = configuration
        self.fcsan = None
        self.huawei_conf = FakeHuaweiConf(self.configuration, 'iSCSI')
        self.active_backend_id = None
        self.replica = None
        self.support_func = None

    def do_setup(self):
        self.metro_flag = True
        self.huawei_conf.update_config_value()
        self.get_local_and_remote_dev_conf()

        self.client = FakeClient(configuration=self.configuration)
        self.rmt_client = FakeClient(configuration=self.configuration)
        self.replica_client = FakeClient(configuration=self.configuration)
        self.metro = hypermetro.HuaweiHyperMetro(self.client,
                                                 self.rmt_client,
                                                 self.configuration)
        self.replica = FakeReplicaPairManager(self.client,
                                              self.replica_client,
                                              self.configuration)


@ddt.ddt
class HuaweiTestBase(test.TestCase):
    """Base class for Huawei test cases.

    Implement common setup operations or test cases in this class.
    """

    def setUp(self):
        super(HuaweiTestBase, self).setUp()
        self.configuration = mock.Mock(spec=conf.Configuration)
        self.driver = FakeISCSIStorage(configuration=self.configuration)
        self.driver.do_setup()

        self.volume = fake_volume.fake_volume_obj(
            admin_contex, host=HOST, provider_location=PROVIDER_LOCATION,
            metadata=METADATA, id=ID)

        self.snapshot = fake_snapshot.fake_snapshot_obj(
            admin_contex, provider_location=SNAP_PROVIDER_LOCATION, id=ID)

        self.snapshot.volume = self.volume

        self.replica_volume = fake_volume.fake_volume_obj(
            admin_contex, host=HOST, provider_location=PROVIDER_LOCATION,
            volume_metadata=METADATA, replication_status='disabled',
            replication_driver_data=REPLICA_DRIVER_DATA, id=ID)

        self.hyper_volume = fake_volume.fake_volume_obj(
            admin_contex, host=HOST,
            provider_location=PROVIDER_LOCATION_WITH_HYPERMETRO,
            id=ID)

        self.original_volume = fake_volume.fake_volume_obj(admin_contex,
                                                           id=ID)

        self.current_volume = fake_volume.fake_volume_obj(
            admin_contex, id=ID, provider_location=PROVIDER_LOCATION,
            name_id=ID)

        self.group_snapshot = fake_group_snapshot.fake_group_snapshot_obj(
            admin_contex, id=ID, group_id=ID, status='available')

        self.group = fake_group.fake_group_obj(
            admin_contex, id=ID, status='available')

        constants.DEFAULT_REPLICA_WAIT_INTERVAL = .1
        constants.DEFAULT_REPLICA_WAIT_TIMEOUT = .5
        constants.DEFAULT_WAIT_INTERVAL = .1
        constants.DEFAULT_WAIT_TIMEOUT = .5
        constants.MIGRATION_WAIT_INTERVAL = .1

        constants.QOS_SPEC_KEYS = (
            'maxIOPS', 'minIOPS', 'minBandWidth',
            'maxBandWidth', 'latency', 'IOType')
        constants.QOS_IOTYPES = ('0', '1', '2')
        constants.SUPPORT_LUN_TYPES = ('Thick', 'Thin')
        constants.DEFAULT_LUN_TYPE = 'Thick'

    def test_encode_name(self):
        lun_name = huawei_utils.encode_name(self.volume.id)
        self.assertEqual('21ec7341-ca82ece92e1ac480c963f1', lun_name)

    @ddt.data({'name': '9548e5e7-ca1c-46bf-b132',
               'expected': '9548e5e7-ca1c-46bf-b132'},
              {'name': '9548e5e7ca1c46bfb132891b425a81f',
               'expected': '9548e5e7ca1c46bfb132891b425a81f'},
              {'name': '9548e5e7-ca1c-46bf-b132-891b425a81f5',
               'expected': '45d6964d772b2efcaad0e3c59538ecc'})
    @ddt.unpack
    def test_encode_host_name(self, name, expected):
        self.assertEqual(expected, huawei_utils.encode_host_name(name))

    @mock.patch.object(rest_client, 'RestClient')
    def test_create_snapshot_success(self, mock_client):
        lun_info = self.driver.create_snapshot(self.snapshot)
        self.assertDictEqual(
            {"huawei_snapshot_id": "11", "huawei_snapshot_wwn": "fake-wwn"},
            json.loads(lun_info['provider_location']))

        self.snapshot.volume_id = ID
        self.snapshot.volume = self.volume
        lun_info = self.driver.create_snapshot(self.snapshot)
        self.assertDictEqual(
            {"huawei_snapshot_id": "11", "huawei_snapshot_wwn": "fake-wwn"},
            json.loads(lun_info['provider_location']))

    @ddt.data('1', '', '0')
    def test_copy_volume(self, input_speed):
        self.driver.configuration.lun_copy_wait_interval = 0
        self.volume.metadata = {'copyspeed': input_speed}

        mocker = self.mock_object(
            self.driver.client, 'create_luncopy',
            mock.Mock(wraps=self.driver.client.create_luncopy))

        self.driver._copy_volume(self.volume,
                                 'fake_copy_name',
                                 'fake_src_lun',
                                 'fake_tgt_lun')

        mocker.assert_called_once_with('fake_copy_name',
                                       'fake_src_lun',
                                       'fake_tgt_lun',
                                       input_speed)

    @ddt.data({'input_speed': '1',
               'actual_speed': '1'},
              {'input_speed': '',
               'actual_speed': '2'},
              {'input_speed': None,
               'actual_speed': '2'},
              {'input_speed': '5',
               'actual_speed': '2'})
    @ddt.unpack
    def test_client_create_luncopy(self, input_speed, actual_speed):
        mocker = self.mock_object(
            self.driver.client, 'call',
            mock.Mock(wraps=self.driver.client.call))

        self.driver.client.create_luncopy('fake_copy_name',
                                          'fake_src_lun',
                                          'fake_tgt_lun',
                                          input_speed)

        mocker.assert_called_once_with(
            mock.ANY,
            {"TYPE": 219,
             "NAME": 'fake_copy_name',
             "DESCRIPTION": 'fake_copy_name',
             "COPYSPEED": actual_speed,
             "LUNCOPYTYPE": "1",
             "SOURCELUN": "INVALID;fake_src_lun;INVALID;INVALID;INVALID",
             "TARGETLUN": "INVALID;fake_tgt_lun;INVALID;INVALID;INVALID"},
            'POST'
        )

    @ddt.data(
        {
            'volume': fake_volume.fake_volume_obj(
                admin_contex,
                provider_location=PROVIDER_LOCATION),
            'expect': {'huawei_lun_id': '11',
                       'huawei_lun_wwn': '6643e8c1004c5f6723e9f454003'}
        },
        {
            'volume': fake_volume.fake_volume_obj(
                admin_contex,
                provider_location=None),
            'expect': {}
        },
        {
            'volume': fake_volume.fake_volume_obj(
                admin_contex,
                provider_location=''),
            'expect': {}
        },
        {
            'volume': fake_volume.fake_volume_obj(
                admin_contex,
                provider_location='11',
                volume_admin_metadata=ADMIN_METADATA,
                volume_metadata=VOL_METADATA
            ),
            'expect': {'huawei_lun_id': '11',
                       'huawei_lun_wwn': 'FAKE_WWN',
                       'huawei_sn': None,
                       'hypermetro_id': '11',
                       'remote_lun_id': '1'}
        }
    )
    @ddt.unpack
    def test_get_volume_private_data(self, volume, expect):
        metadata = huawei_utils.get_volume_private_data(volume)
        self.assertEqual(expect, metadata)

    @ddt.data(
        {
            'snapshot': fake_snapshot.fake_snapshot_obj(
                admin_contex,
                provider_location=SNAP_PROVIDER_LOCATION),
            'expect': {'huawei_snapshot_id': '11'}
        },
        {
            'snapshot': fake_snapshot.fake_snapshot_obj(
                admin_contex,
                provider_location=None),
            'expect': {}
        },
        {
            'snapshot': fake_snapshot.fake_snapshot_obj(
                admin_contex,
                provider_location=''),
            'expect': {}
        },
        {
            'snapshot': fake_snapshot.fake_snapshot_obj(
                admin_contex,
                provider_location='11',
                snapshot_metadata=[{'key': 'huawei_snapshot_wwn',
                                    'value': 'fake_wwn'},
                                   ],
                expected_attrs=['metadata'],
            ),
            'expect': {'huawei_snapshot_id': '11',
                       'huawei_snapshot_wwn': 'fake_wwn',
                       }
        }
    )
    @ddt.unpack
    def test_get_snapshot_private_data(self, snapshot, expect):
        metadata = huawei_utils.get_snapshot_private_data(snapshot)
        self.assertDictEqual(expect, metadata)

    @ddt.data(
        {
            'provider_location': PROVIDER_LOCATION,
            'mock_func': None,
        },
        {
            'provider_location': '',
            'mock_func': None,
        },
        {
            'provider_location': PROVIDER_LOCATION,
            'mock_func': 'get_lun_info_by_name',
        },
        {
            'provider_location': '{"huawei_lun_wwn": "fake_wwn"}',
            'mock_func': None,
        },
    )
    @ddt.unpack
    def test_get_lun_info(self, provider_location, mock_func):
        volume = fake_volume.fake_volume_obj(
            admin_contex, id=ID, provider_location=provider_location)

        if mock_func:
            self.mock_object(self.driver.client, mock_func, return_value=None)
        lun_info = huawei_utils.get_lun_info(self.driver.client, volume)

        if provider_location in (PROVIDER_LOCATION, ''):
            self.assertEqual('6643e8c1004c5f6723e9f454003', lun_info['WWN'])
        else:
            self.assertIsNone(lun_info)

    @ddt.data(
        {
            'snapshot': fake_snapshot.fake_snapshot_obj(
                admin_contex, id=ID),
            'expect': '11',
        },
        {
            'snapshot': fake_snapshot.fake_snapshot_obj(
                admin_contex, id=ID2),
            'expect': '11',
        },
        {
            'snapshot': fake_snapshot.fake_snapshot_obj(
                admin_contex, id='e9c9ca0f-01e8-4780-9585-369c15026001'),
            'expect': None
        }
    )
    @ddt.unpack
    def test_get_snapshot_info(self, snapshot, expect):
        snapshot_info = huawei_utils.get_snapshot_info(
            self.driver.client, snapshot)
        if expect:
            self.assertEqual(expect, snapshot_info['ID'])
        else:
            self.assertIsNone(snapshot_info)

    @ddt.data(
        {'host_name': HOST,
         'expect': '1'},
        {'host_name': HOST2,
         'expect': '1'},
        {'host_name': 'fake_host_name',
         'expect': None},
    )
    @ddt.unpack
    def test_get_host_id(self, host_name, expect):
        host_id = huawei_utils.get_host_id(self.driver.client,
                                           host_name)
        self.assertEqual(expect, host_id)


@ddt.ddt
class HuaweiISCSIDriverTestCase(HuaweiTestBase):

    def setUp(self):
        super(HuaweiISCSIDriverTestCase, self).setUp()
        self.configuration = mock.Mock(spec=conf.Configuration)
        self.configuration.hypermetro_devices = hypermetro_devices
        self.flags(transport_url='fake:/')
        self.driver = FakeISCSIStorage(configuration=self.configuration)
        self.driver.do_setup()
        self.portgroup = 'portgroup-test'
        self.iscsi_iqns = ['iqn.2006-08.com.huawei:oceanstor:21000022a:'
                           ':20503:192.0.2.1',
                           'iqn.2006-08.com.huawei:oceanstor:21000022a:'
                           ':20500:192.0.2.2']
        self.target_ips = ['192.0.2.1',
                           '192.0.2.2']
        self.portgroup_id = 11
        self.driver.client.login()

    def test_parse_rmt_iscsi_info(self):
        rmt_dev = self.driver.configuration.replication
        expected_iscsi_info = {'Name': 'iqn.1993-08.debian:01:ec2bff7acxxx',
                               'TargetIP': '1.1.1.1',
                               'CHAPinfo': 'mm-user;mm-user@storage',
                               'ALUA': '1',
                               'TargetPortGroup': 'portgroup-test'}
        self.assertDictEqual(expected_iscsi_info, rmt_dev['iscsi_info'])

    def test_login_success(self):
        device_id = self.driver.client.login()
        self.assertEqual('210235G7J20000000000', device_id)

    @ddt.data(constants.PWD_EXPIRED, constants.PWD_RESET)
    def test_login_password_expires_and_reset_fail(self, state):
        with mock.patch.object(self.driver.client, 'logout') as mock_logout:
            self.mock_object(FakeClient, 'do_call',
                             return_value={"error": {"code": 0},
                                           "data": {
                                           "username": "admin",
                                           "iBaseToken": "2001031430",
                                           "deviceid": "210235G7J20000000000",
                                           "accountstate": state}})
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.driver.client.login)
            mock_logout.assert_called_once_with()

    def test_login_logout_fail(self):
        login_info = {"error": {"code": 0},
                      "data": {"username": "admin",
                               "iBaseToken": "2001031430",
                               "deviceid": "210235G7J20000000000",
                               "accountstate": 3}}
        logout_info = {"error": {"code": 1}, "data": {}}
        self.mock_object(FakeClient, 'do_call',
                         side_effect=[login_info, logout_info])
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.client.login)

    def test_check_volume_exist_on_array(self):
        self.mock_object(rest_client.RestClient, 'get_lun_id_by_name',
                         return_value=None)
        self.driver._check_volume_exist_on_array(
            self.volume, constants.VOLUME_NOT_EXISTS_WARN)

    def test_create_volume_success(self):
        # Have pool info in the volume.
        self.volume.host = 'ubuntu001@backend001#OpenStack_Pool'

        lun_info = self.driver.create_volume(self.volume)
        expect_value = {"huawei_lun_id": "1",
                        "huawei_lun_wwn": "6643e8c1004c5f6723e9f454003"}
        self.assertDictEqual(expect_value,
                             json.loads(lun_info['provider_location']))

        # No pool info in the volume.
        self.volume.host = 'ubuntu001@backend001'
        lun_info = self.driver.create_volume(self.volume)
        expect_value = {"huawei_lun_id": "1",
                        "huawei_lun_wwn": "6643e8c1004c5f6723e9f454003"}
        self.assertDictEqual(expect_value,
                             json.loads(lun_info['provider_location']))

    @ddt.data(FAKE_POOLS_UNSUPPORT_REPORT, FAKE_POOLS_SUPPORT_REPORT)
    def test_delete_replication_fail(self, pool_data):
        self.driver.support_func = pool_data
        self.mock_object(replication.ReplicaCommonDriver, 'split')
        self.mock_object(
            common.HuaweiBaseDriver,
            '_get_volume_type',
            return_value={'extra_specs': sync_replica_specs})
        self.mock_object(rest_client.RestClient,
                         'delete_lun',
                         side_effect=exception.VolumeBackendAPIException(
                             data='err'))
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_volume, self.replica_volume)

    @ddt.data(FAKE_POOLS_UNSUPPORT_REPORT, FAKE_POOLS_SUPPORT_REPORT)
    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new=utils.ZeroIntervalLoopingCall)
    def test_migrate_volume_success_no_data(self, pool_data):
        self.driver.support_func = pool_data
        task_info = {"data": [{"ENDTIME": "1436816174",
                               "ID": "9",
                               "PARENTID": "11",
                               "PARENTNAME": "xmRBHMlVRruql5vwthpPXQ",
                               "PROCESS": "-1",
                               "RUNNINGSTATUS": "76",
                               "SPEED": "2",
                               "STARTTIME": "1436816111",
                               "TARGETLUNID": "1",
                               "TARGETLUNNAME": "4924891454902893639",
                               "TYPE": 253,
                               "WORKMODE": "0"
                               }],
                     "error": {"code": 0,
                               "description": "0"}
                     }
        moved = False
        empty_dict = {}
        self.mock_object(rest_client.RestClient, 'get_lun_migration_task',
                         side_effect=[{}, task_info])
        moved, model_update = self.driver.migrate_volume(None,
                                                         self.volume,
                                                         test_host)
        self.assertTrue(moved)
        self.assertEqual(empty_dict, model_update)

    @ddt.data(FAKE_POOLS_UNSUPPORT_REPORT, FAKE_POOLS_SUPPORT_REPORT)
    def test_migrate_volume_success_with_replication(self, pool_data):
        self.driver.support_func = pool_data
        task_info = {"data": [{"ENDTIME": "1436816174",
                               "ID": "9",
                               "PARENTID": "11",
                               "PARENTNAME": "xmRBHMlVRruql5vwthpPXQ",
                               "PROCESS": "-1",
                               "RUNNINGSTATUS": "76",
                               "SPEED": "2",
                               "STARTTIME": "1436816111",
                               "TARGETLUNID": "1",
                               "TARGETLUNNAME": "4924891454902893639",
                               "TYPE": 253,
                               "WORKMODE": "0"
                               }],
                     "error": {"code": 0,
                               "description": "0"}
                     }
        moved = False
        empty_dict = {}
        self.mock_object(rest_client.RestClient, 'get_lun_migration_task',
                         return_value=task_info)
        moved, model_update = self.driver.migrate_volume(None,
                                                         self.replica_volume,
                                                         test_host)
        self.assertTrue(moved)
        self.assertEqual(empty_dict, model_update)

    @ddt.data(FAKE_POOLS_UNSUPPORT_REPORT, FAKE_POOLS_SUPPORT_REPORT)
    def test_migrate_volume_fail_migration_fault(self, pool_data):
        self.driver.support_func = pool_data
        task_info = {"data": [{"ENDTIME": "1436816174",
                               "ID": "9",
                               "PARENTID": "11",
                               "PARENTNAME": "xmRBHMlVRruql5vwthpPXQ",
                               "PROCESS": "-1",
                               "RUNNINGSTATUS": "74",
                               "SPEED": "2",
                               "STARTTIME": "1436816111",
                               "TARGETLUNID": "1",
                               "TARGETLUNNAME": "4924891454902893639",
                               "TYPE": 253,
                               "WORKMODE": "0"
                               }],
                     "error": {"code": 0,
                               "description": "0"}
                     }
        self.mock_object(rest_client.RestClient, 'get_lun_migration_task',
                         return_value=task_info)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.migrate_volume,
                          None, self.volume, test_host)

    @ddt.data(FAKE_POOLS_UNSUPPORT_REPORT, FAKE_POOLS_SUPPORT_REPORT)
    def test_migrate_volume_fail_no_migrate_task(self, pool_data):
        self.driver.support_func = pool_data
        task_info = {"data": [{"ENDTIME": "1436816174",
                               "ID": "9",
                               "PARENTID": "12",
                               "PARENTNAME": "xmRBHMlVRruql5vwthpPXQ",
                               "PROCESS": "-1",
                               "RUNNINGSTATUS": "76",
                               "SPEED": "2",
                               "STARTTIME": "1436816111",
                               "TARGETLUNID": "1",
                               "TARGETLUNNAME": "4924891454902893639",
                               "TYPE": 253,
                               "WORKMODE": "0"
                               }],
                     "error": {"code": 0,
                               "description": "0"}
                     }
        self.mock_object(rest_client.RestClient, 'get_lun_migration_task',
                         return_value=task_info)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.migrate_volume,
                          None, self.volume, test_host)

    @ddt.data(FAKE_POOLS_UNSUPPORT_REPORT, FAKE_POOLS_SUPPORT_REPORT)
    def test_migrate_volume_with_type_id(self, pool_data):
        self.driver.support_func = pool_data
        self.volume.volume_type = None
        self.volume.volume_type_id = '550c089b-bfdd-4f7f-86e1-3ba88125555c'
        task_info = {"data": [{"ENDTIME": "1436816174",
                               "ID": "9",
                               "PARENTID": "11",
                               "PARENTNAME": "xmRBHMlVRruql5vwthpPXQ",
                               "PROCESS": "-1",
                               "RUNNINGSTATUS": "76",
                               "SPEED": "2",
                               "STARTTIME": "1436816111",
                               "TARGETLUNID": "1",
                               "TARGETLUNNAME": "4924891454902893639",
                               "TYPE": 253,
                               "WORKMODE": "0"
                               }],
                     "error": {"code": 0,
                               "description": "0"}
                     }
        empty_dict = {}
        self.mock_object(volume_types, 'get_volume_type',
                         return_value=test_new_type)
        self.mock_object(rest_client.RestClient, 'get_lun_migration_task',
                         return_value=task_info)
        moved, model_update = self.driver.migrate_volume(None,
                                                         self.volume,
                                                         test_host)
        self.assertTrue(moved)
        self.assertEqual(empty_dict, model_update)

    @ddt.data(FAKE_POOLS_UNSUPPORT_REPORT, FAKE_POOLS_SUPPORT_REPORT)
    def test_manage_existing_fail(self, pool_data):
        self.driver.support_func = pool_data
        self.mock_object(rest_client.RestClient, 'get_lun_info',
                         return_value={'CAPACITY': 2097152, 'ALLOCTYPE': 1})
        self.mock_object(rest_client.RestClient, 'get_lun_id_by_name',
                         return_value='ID1')
        self.mock_object(rest_client.RestClient, 'rename_lun')
        self.mock_object(common.HuaweiBaseDriver,
                         '_get_lun_info_by_ref',
                         return_value={
                             'PARENTNAME': 'OpenStack_Pool',
                             'SNAPSHOTIDS': [],
                             'ID': 'ID1',
                             'HEALTHSTATUS': constants.STATUS_HEALTH,
                             'WWN': '6643e8c1004c5f6723e9f454003'})
        self.mock_object(volume_types, 'get_volume_type',
                         return_value={'extra_specs': test_new_type})
        self.mock_object(common.HuaweiBaseDriver,
                         '_check_needed_changes',
                         return_value={})
        external_ref = {'source-name': 'test1',
                        'source-id': 'ID1'}

        self.driver.manage_existing(self.volume, external_ref)

    @ddt.data(FAKE_POOLS_UNSUPPORT_REPORT, FAKE_POOLS_SUPPORT_REPORT)
    def test_delete_volume_success(self, pool_data):
        self.driver.support_func = pool_data
        self.driver.delete_volume(self.volume)

    def test_delete_snapshot_success(self):
        self.driver.delete_snapshot(self.snapshot)

    def test_create_volume_from_snapsuccess(self):
        self.mock_object(
            huawei_utils,
            'get_volume_params',
            return_value={'replication_enabled': True})
        self.mock_object(replication.ReplicaCommonDriver, 'sync')
        model_update = self.driver.create_volume_from_snapshot(self.volume,
                                                               self.snapshot)
        expect_value = {"huawei_lun_id": "1",
                        "huawei_lun_wwn": "6643e8c1004c5f6723e9f454003"}
        self.assertDictEqual(expect_value,
                             json.loads(model_update['provider_location']))

        driver_data = {'pair_id': TEST_PAIR_ID,
                       'rmt_lun_id': '1',
                       'rmt_lun_wwn': '6643e8c1004c5f6723e9f454003'}
        self.assertDictEqual(
            driver_data, json.loads(model_update['replication_driver_data']))
        self.assertEqual('available', model_update['replication_status'])

    @mock.patch.object(huawei_driver.HuaweiISCSIDriver,
                       'initialize_connection',
                       return_value={"data": {'target_lun': 1}})
    def test_initialize_connection_snapshot_success(self, mock_iscsi_init):
        iscsi_properties = self.driver.initialize_connection_snapshot(
            self.snapshot, FakeConnector)
        volume = Volume(id=self.snapshot.id,
                        provider_location=self.snapshot.provider_location,
                        lun_type='27',
                        metadata=None)
        self.assertEqual(1, iscsi_properties['data']['target_lun'])
        mock_iscsi_init.assert_called_with(volume, FakeConnector)

    def test_initialize_connection_success_multipath_portgroup(self):
        temp_connector = copy.deepcopy(FakeConnector)
        temp_connector['multipath'] = True
        self.mock_object(rest_client.RestClient, 'get_tgt_port_group',
                         return_value='11')
        iscsi_properties = self.driver.initialize_connection(self.volume,
                                                             temp_connector)
        self.assertEqual([1, 1], iscsi_properties['data']['target_luns'])

    def test_initialize_connection_fail_multipath_portgroup(self):
        temp_connector = copy.deepcopy(FakeConnector)
        temp_connector['multipath'] = True
        self.mock_object(rest_client.RestClient, 'get_tgt_port_group',
                         return_value='12')
        self.mock_object(rest_client.RestClient, '_get_tgt_ip_from_portgroup',
                         return_value=[])
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          self.volume, temp_connector)

    def test_initialize_connection_success_multipath_targetip(self):
        iscsi_info = {
            'initiators': {
                'iqn.1993-08.debian:01:ec2bff7ac3a3': {
                    'Name': 'iqn.1993-08.debian:01:ec2bff7ac3a3',
                    'TargetIP': '192.0.2.2',
                    'CHAPinfo': 'mm-user;mm-user@storage',
                    'ALUA': '1',
                }
            }
        }

        configuration = mock.Mock(spec=conf.Configuration)
        configuration.hypermetro_devices = hypermetro_devices
        driver = FakeISCSIStorage(configuration=self.configuration)
        driver.do_setup()
        driver.configuration.iscsi_info = iscsi_info
        driver.client.iscsi_info = iscsi_info
        temp_connector = copy.deepcopy(FakeConnector)
        temp_connector['multipath'] = True
        iscsi_properties = driver.initialize_connection(self.volume,
                                                        temp_connector)
        self.assertEqual([1], iscsi_properties['data']['target_luns'])

    def test_initialize_connection_fail_multipath_targetip(self):
        iscsi_info = {
            'initiators': {
                'iqn.1993-08.debian:01:ec2bff7ac3a3': {
                    'Name': 'iqn.1993-08.debian:01:ec2bff7ac3a3',
                    'TargetIP': '192.0.2.6',
                    'CHAPinfo': 'mm-user;mm-user@storage',
                    'ALUA': '1',
                }
            }
        }

        configuration = mock.Mock(spec=conf.Configuration)
        configuration.hypermetro_devices = hypermetro_devices
        driver = FakeISCSIStorage(configuration=self.configuration)
        driver.do_setup()
        driver.configuration.iscsi_info = iscsi_info
        driver.client.iscsi_info = iscsi_info
        temp_connector = copy.deepcopy(FakeConnector)
        temp_connector['multipath'] = True
        self.assertRaises(exception.VolumeBackendAPIException,
                          driver.initialize_connection,
                          self.volume, temp_connector)

    def test_initialize_connection_success_multipath_defaultip(self):
        iscsi_info = {
            'default_target_ips': ['192.0.2.2'],
            'initiators': {
                'iqn.1993-08.debian:01:ec2bff7ac3a3': {
                    'Name': 'iqn.1993-08.debian:01:ec2bff7ac3a3',
                    'CHAPinfo': 'mm-user;mm-user@storage',
                    'ALUA': '1',
                }
            }
        }

        configuration = mock.Mock(spec=conf.Configuration)
        configuration.hypermetro_devices = hypermetro_devices
        driver = FakeISCSIStorage(configuration=self.configuration)
        driver.do_setup()
        driver.configuration.iscsi_info = iscsi_info
        driver.client.iscsi_info = iscsi_info
        temp_connector = copy.deepcopy(FakeConnector)
        temp_connector['multipath'] = True
        iscsi_properties = driver.initialize_connection(self.volume,
                                                        temp_connector)
        self.assertEqual([1], iscsi_properties['data']['target_luns'])

    def test_initialize_connection_fail_multipath_defaultip(self):
        iscsi_info = {
            'default_target_ips': ['192.0.2.6'],
            'initiators': {
                'iqn.1993-08.debian:01:ec2bff7ac3a3': {
                    'Name': 'iqn.1993-08.debian:01:ec2bff7ac3a3',
                    'CHAPinfo': 'mm-user;mm-user@storage',
                    'ALUA': '1',
                }
            },
        }

        configuration = mock.Mock(spec=conf.Configuration)
        configuration.hypermetro_devices = hypermetro_devices
        driver = FakeISCSIStorage(configuration=self.configuration)
        driver.do_setup()
        driver.configuration.iscsi_info = iscsi_info
        driver.client.iscsi_info = iscsi_info
        temp_connector = copy.deepcopy(FakeConnector)
        temp_connector['multipath'] = True
        self.assertRaises(exception.VolumeBackendAPIException,
                          driver.initialize_connection,
                          self.volume, temp_connector)

    def test_initialize_connection_fail_no_port_in_portgroup(self):
        temp_connector = copy.deepcopy(FakeConnector)
        temp_connector['multipath'] = True
        self.mock_object(rest_client.RestClient, 'get_tgt_port_group',
                         return_value='11')
        self.mock_object(rest_client.RestClient, '_get_tgt_ip_from_portgroup',
                         return_value=[])
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          self.volume, temp_connector)

    def test_initialize_connection_fail_multipath_no_ip(self):
        iscsi_info = {
            'default_target_ips': [],
            'initiators': {
                'iqn.1993-08.debian:01:ec2bff7ac3a3': {
                    'Name': 'iqn.1993-08.debian:01:ec2bff7ac3a3',
                    'CHAPinfo': 'mm-user;mm-user@storage',
                    'ALUA': '1',
                }
            }
        }

        configuration = mock.Mock(spec=conf.Configuration)
        configuration.hypermetro_devices = hypermetro_devices
        driver = FakeISCSIStorage(configuration=self.configuration)
        driver.do_setup()
        driver.configuration.iscsi_info = iscsi_info
        driver.client.iscsi_info = iscsi_info
        temp_connector = copy.deepcopy(FakeConnector)
        temp_connector['multipath'] = True
        self.assertRaises(exception.VolumeBackendAPIException,
                          driver.initialize_connection,
                          self.volume, temp_connector)

    @mock.patch.object(huawei_driver.HuaweiISCSIDriver,
                       'terminate_connection')
    def test_terminate_connection_snapshot_success(self, mock_iscsi_term):
        self.driver.terminate_connection_snapshot(self.snapshot,
                                                  FakeConnector)
        volume = Volume(id=self.snapshot.id,
                        provider_location=self.snapshot.provider_location,
                        lun_type='27',
                        metadata=None)
        mock_iscsi_term.assert_called_with(volume, FakeConnector)

    def test_terminate_connection_success(self):
        self.driver.terminate_connection(self.volume, FakeConnector)

    def test_get_volume_status(self):
        data = self.driver.get_volume_stats()
        self.assertEqual(self.driver.VERSION, data['driver_version'])

    @mock.patch.object(rest_client.RestClient, 'get_lun_info',
                       return_value={"CAPACITY": 6291456})
    @mock.patch.object(rest_client.RestClient, 'extend_lun')
    def test_extend_volume_size_equal(self, mock_extend, mock_lun_info):
        self.driver.extend_volume(self.volume, 3)
        self.assertEqual(0, mock_extend.call_count)

    @mock.patch.object(rest_client.RestClient, 'get_lun_info',
                       return_value={"CAPACITY": 5291456})
    @mock.patch.object(rest_client.RestClient, 'extend_lun')
    def test_extend_volume_success(self, mock_extend, mock_lun_info):
        self.driver.extend_volume(self.volume, 3)
        self.assertEqual(1, mock_extend.call_count)

    @mock.patch.object(rest_client.RestClient, 'get_lun_info',
                       return_value={"CAPACITY": 7291456})
    def test_extend_volume_fail(self, mock_lun_info):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.extend_volume, self.volume, 3)

    def test_extend_nonexistent_volume(self):
        self.volume = fake_volume.fake_volume_obj(admin_contex)
        self.mock_object(rest_client.RestClient,
                         'get_lun_id_by_name',
                         return_value=None)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.extend_volume,
                          self.volume, 3)

    def test_get_volume_metadata(self):
        metadata = [{'key': 'huawei_lun_wwn', 'value': '1'}]
        tmp_volume = fake_volume.fake_volume_obj(
            admin_contex, volume_metadata=metadata)
        expected_value = {'huawei_lun_wwn': '1'}
        metadata = huawei_utils.get_volume_metadata(tmp_volume)
        self.assertEqual(expected_value, metadata)

        expected_value = {'huawei_lun_wwn': '1'}
        tmp_volume = fake_volume.fake_volume_obj(admin_contex)
        tmp_volume.metadata = expected_value
        metadata = huawei_utils.get_volume_metadata(tmp_volume)
        self.assertEqual(expected_value, metadata)

    def test_login_fail(self):
        self.driver.client.test_fail = True
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.client.login)

    def test_create_snapshot_fail(self):
        self.driver.client.test_fail = True
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_snapshot, self.snapshot)

    def test_create_volume_fail(self):
        self.driver.client.test_fail = True
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume, self.volume)

    def test_delete_volume_fail(self):
        self.mock_object(
            self.driver.client, 'delete_lun',
            side_effect=exception.VolumeBackendAPIException(data=''))
        self.driver.support_func = {}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_volume, self.volume)

    def test_delete_snapshot_fail(self):
        self.driver.client.test_fail = True
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_snapshot, self.snapshot)

    def test_delete_snapshot_with_snapshot_nonexistent(self):
        self.snapshot.provider_location = None
        self.driver.delete_snapshot(self.snapshot)

    def test_initialize_connection_fail(self):
        self.driver.client.test_fail = True

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          self.volume, FakeConnector)

    def test_lun_is_associated_to_lungroup(self):
        self.driver.client.associate_lun_to_lungroup('11', '11')
        result = self.driver.client._is_lun_associated_to_lungroup('11',
                                                                   '11')
        self.assertTrue(result)

    def test_lun_is_not_associated_to_lun_group(self):
        self.driver.client.associate_lun_to_lungroup('12', '12')
        self.driver.client.remove_lun_from_lungroup('12', '12')
        result = self.driver.client._is_lun_associated_to_lungroup('12', '12')
        self.assertFalse(result)

    def test_get_tgtip(self):
        portg_id = self.driver.client.get_tgt_port_group(self.portgroup)
        target_ip = self.driver.client._get_tgt_ip_from_portgroup(portg_id)
        self.assertEqual(self.target_ips, target_ip)

    def test_find_chap_info(self):
        iscsi_info = {
            'initiators': {
                'fake.iqn': {
                    'Name': 'fake.iqn',
                    'CHAPinfo': 'mm-user;mm-user@storage',
                }
            }
        }

        chapinfo = self.driver.client.find_chap_info(iscsi_info, 'fake.iqn')
        chap_username, chap_password = chapinfo.split(';')
        self.assertEqual('mm-user', chap_username)
        self.assertEqual('mm-user@storage', chap_password)

    def test_find_alua_info(self):
        iscsi_info = {
            'initiators': {
                'fake.iqn': {
                    'Name': 'fake.iqn',
                    'ALUA': '1',
                }
            }
        }

        type = self.driver.client._find_alua_info(iscsi_info, 'fake.iqn')
        self.assertEqual('1', type)

    def test_get_pool_info(self):
        pools = [{"NAME": "test001",
                  "ID": "0",
                  "USERFREECAPACITY": "36",
                  "USERTOTALCAPACITY": "48",
                  "USAGETYPE": constants.BLOCK_STORAGE_POOL_TYPE,
                  "TIER0CAPACITY": "48",
                  "TIER1CAPACITY": "0",
                  "TIER2CAPACITY": "0"},
                 {"NAME": "test002",
                  "ID": "1",
                  "USERFREECAPACITY": "37",
                  "USERTOTALCAPACITY": "49",
                  "USAGETYPE": constants.FILE_SYSTEM_POOL_TYPE,
                  "TIER0CAPACITY": "0",
                  "TIER1CAPACITY": "49",
                  "TIER2CAPACITY": "0"},
                 {"NAME": "test003",
                  "ID": "0",
                  "USERFREECAPACITY": "36",
                  "DATASPACE": "35",
                  "USERTOTALCAPACITY": "48",
                  "USAGETYPE": constants.BLOCK_STORAGE_POOL_TYPE,
                  "TIER0CAPACITY": "0",
                  "TIER1CAPACITY": "0",
                  "TIER2CAPACITY": "48"},
                 {"NAME": "test004",
                  "ID": "0",
                  "USERFREECAPACITY": "36",
                  "DATASPACE": "35",
                  "USERTOTALCAPACITY": "48",
                  "USAGETYPE": constants.BLOCK_STORAGE_POOL_TYPE,
                  "TIER0CAPACITY": "40"}]
        pool_name = 'test001'
        test_info = {'CAPACITY': '36', 'ID': '0', 'TOTALCAPACITY': '48',
                     'TIER0CAPACITY': '48', 'TIER1CAPACITY': '0',
                     'TIER2CAPACITY': '0'}
        pool_info = self.driver.client.get_pool_info(pool_name, pools)
        self.assertEqual(test_info, pool_info)

        pool_name = 'test002'
        test_info = {}
        pool_info = self.driver.client.get_pool_info(pool_name, pools)
        self.assertEqual(test_info, pool_info)

        pool_name = 'test000'
        test_info = {}
        pool_info = self.driver.client.get_pool_info(pool_name, pools)
        self.assertEqual(test_info, pool_info)

        pool_name = 'test003'
        test_info = {'CAPACITY': '35', 'ID': '0', 'TOTALCAPACITY': '48',
                     'TIER0CAPACITY': '0', 'TIER1CAPACITY': '0',
                     'TIER2CAPACITY': '48'}
        pool_info = self.driver.client.get_pool_info(pool_name, pools)
        self.assertEqual(test_info, pool_info)

        pool_name = 'test004'
        test_info = {'CAPACITY': '35', 'ID': '0', 'TOTALCAPACITY': '48',
                     'TIER0CAPACITY': '40', 'TIER1CAPACITY': '0',
                     'TIER2CAPACITY': '0'}
        pool_info = self.driver.client.get_pool_info(pool_name, pools)
        self.assertEqual(test_info, pool_info)

    @ddt.data(FAKE_POOLS_UNSUPPORT_REPORT, FAKE_POOLS_SUPPORT_REPORT)
    @mock.patch.object(huawei_utils, 'get_volume_params',
                       return_value={'qos': {'MAXIOPS': '100',
                                             'IOType': '2'}
                                     })
    def test_create_smartqos(self, mock_qos_value, pool_data):
        self.driver.support_func = pool_data
        lun_info = self.driver.create_volume(self.volume)
        expect_value = {"huawei_lun_id": "1",
                        "huawei_lun_wwn": "6643e8c1004c5f6723e9f454003"}
        self.assertDictEqual(expect_value,
                             json.loads(lun_info['provider_location']))

    @ddt.data('front-end', 'back-end')
    @mock.patch.object(huawei_utils, 'get_volume_params',
                       return_value={'smarttier': 'true',
                                     'smartcache': 'true',
                                     'smartpartition': 'true',
                                     'thin_provisioning_support': 'true',
                                     'thick_provisioning_support': 'false',
                                     'policy': '2',
                                     'cachename': 'cache-test',
                                     'partitionname': 'partition-test'})
    @mock.patch.object(common.HuaweiBaseDriver, '_get_volume_type',
                       return_value={'qos_specs_id': u'025ce295-15e9-41a7'})
    def test_create_smartqos_success(self,
                                     mock_consumer,
                                     mock_qos_specs,
                                     mock_value_type):
        self.mock_object(qos_specs, 'get_qos_specs',
                         return_value={'specs': {'maxBandWidth': '100',
                                                 'IOType': '0'},
                                       'consumer': mock_consumer})
        self.driver.support_func = FAKE_POOLS_SUPPORT_REPORT
        lun_info = self.driver.create_volume(self.volume)
        expect_value = {"huawei_lun_id": "1",
                        "huawei_lun_wwn": "6643e8c1004c5f6723e9f454003"}
        self.assertDictEqual(expect_value,
                             json.loads(lun_info['provider_location']))

    @ddt.data([{'specs': {'maxBandWidth': '100', 'IOType': '3'}},
               FAKE_POOLS_UNSUPPORT_REPORT],
              [{'specs': {'maxBandWidth': '100', 'IOType': '3'}},
               FAKE_POOLS_SUPPORT_REPORT],
              [{'specs': {'minBandWidth': '0', 'IOType': '2'}},
               FAKE_POOLS_UNSUPPORT_REPORT],
              [{'specs': {'minBandWidth': '0', 'IOType': '2'}},
               FAKE_POOLS_SUPPORT_REPORT])
    @ddt.unpack
    def test_create_smartqos_failed(self, qos_specs_value, pool_data):
        self.driver.support_func = pool_data
        self.mock_object(qos_specs, 'get_qos_specs',
                         return_value=qos_specs_value)
        self.volume.volume_type = objects.VolumeType(
            extra_specs={}, qos_specs_id=ID)
        self.assertRaises(exception.InvalidInput,
                          self.driver.create_volume, self.volume)

    @ddt.data(FAKE_POOLS_UNSUPPORT_REPORT, FAKE_POOLS_SUPPORT_REPORT)
    def test_create_smartqos_without_huawei_type(self, pool_data):
        self.driver.support_func = pool_data
        self.mock_object(qos_specs, 'get_qos_specs',
                         return_value={'specs': {'fake_qos_type': '100',
                                                 'IOType': '2'}}
                         )
        self.volume.volume_type = objects.VolumeType(
            extra_specs={}, qos_specs_id=ID)
        self.assertRaises(exception.InvalidInput,
                          self.driver.create_volume, self.volume)

    @mock.patch.object(huawei_utils, 'get_volume_params',
                       return_value={'qos': {'MAXIOPS': '100',
                                             'IOType': '2'}
                                     })
    @mock.patch.object(rest_client.RestClient, 'find_array_version',
                       return_value='V300R003C00')
    @mock.patch.object(rest_client.RestClient, 'find_available_qos',
                       return_value=(None, []))
    def test_create_smartqos_on_v3r3_with_no_qos(self,
                                                 mock_find_available_qos,
                                                 mock_qos_value,
                                                 mock_array_version):
        self.driver.support_func = FAKE_POOLS_SUPPORT_REPORT
        lun_info = self.driver.create_volume(self.volume)
        expect_value = {"huawei_lun_id": "1",
                        "huawei_lun_wwn": "6643e8c1004c5f6723e9f454003"}
        self.assertDictEqual(expect_value,
                             json.loads(lun_info['provider_location']))

    @mock.patch.object(huawei_utils, 'get_volume_params',
                       return_value={'qos': {'MAXIOPS': '100',
                                             'IOType': '2'}
                                     })
    @mock.patch.object(rest_client.RestClient, 'find_array_version',
                       return_value='V300R003C00')
    @mock.patch.object(rest_client.RestClient, 'find_available_qos',
                       return_value=('11', u'["0", "2", "3"]'))
    def test_create_smartqos_on_v3r3_with_qos(self,
                                              mock_find_available_qos,
                                              mock_qos_value,
                                              mock_array_version):
        self.driver.support_func = FAKE_POOLS_SUPPORT_REPORT
        lun_info = self.driver.create_volume(self.volume)
        expect_value = {"huawei_lun_id": "1",
                        "huawei_lun_wwn": "6643e8c1004c5f6723e9f454003"}
        self.assertDictEqual(expect_value,
                             json.loads(lun_info['provider_location']))

    @ddt.data(FAKE_POOLS_UNSUPPORT_REPORT, FAKE_POOLS_SUPPORT_REPORT)
    def test_create_smartqos_on_v3r3_active_failed(self, pool_data):
        self.driver.support_func = pool_data

        self.mock_object(huawei_utils, 'get_volume_params',
                         return_value={'qos': {'MAXIOPS': '100',
                                               'IOType': '2'}
                                       }
                         )
        self.mock_object(self.driver.client, 'activate_deactivate_qos',
                         side_effect=exception.VolumeBackendAPIException(
                             data='Activate or deactivate QoS error.')
                         )
        self.mock_object(smartx.SmartQos, 'remove')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume, self.volume)

    @ddt.data(FAKE_POOLS_UNSUPPORT_REPORT, FAKE_POOLS_SUPPORT_REPORT)
    @mock.patch.object(huawei_utils, 'get_volume_params',
                       return_value={'qos': {'MAXIOPS': '100',
                                             'IOType': '2'}
                                     })
    @mock.patch.object(rest_client.RestClient, 'find_array_version',
                       return_value='V300R003C00')
    @mock.patch.object(rest_client.RestClient, 'find_available_qos',
                       return_value=(None, []))
    @mock.patch.object(rest_client.RestClient, 'create_qos')
    def test_create_smartqos_on_v3r3_qos_failed(self,
                                                pool_data,
                                                mock_create_qos,
                                                mock_find_available_qos,
                                                mock_qos_value,
                                                mock_array_version):
        self.driver.support_func = pool_data
        mock_create_qos.side_effect = (
            exception.VolumeBackendAPIException(data='Create QoS policy '
                                                'error.'))
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume, self.volume)

    @ddt.data(FAKE_POOLS_UNSUPPORT_REPORT, FAKE_POOLS_SUPPORT_REPORT)
    @mock.patch.object(rest_client.RestClient, 'get_qos_info',
                       return_value={"LUNLIST": u'["1", "2", "3"]',
                                     "RUNNINGSTATUS": "2"})
    def test_delete_smartqos_with_lun_left(self, mock_qos_info, pool_data):
        self.driver.support_func = pool_data
        self.driver.delete_volume(self.volume)

    @ddt.data(FAKE_POOLS_UNSUPPORT_REPORT, FAKE_POOLS_SUPPORT_REPORT)
    @mock.patch.object(rest_client.RestClient, 'get_qos_info',
                       return_value={"LUNLIST": u'["1"]',
                                     "RUNNINGSTATUS": "2"})
    def test_delete_smartqos_with_no_lun_left(self, mock_qos_info, pool_data):
        self.driver.support_func = pool_data
        self.driver.delete_volume(self.volume)

    @mock.patch.object(rest_client.RestClient, 'add_lun_to_partition')
    @mock.patch.object(huawei_utils, 'get_volume_params',
                       return_value={'smarttier': 'true',
                                     'smartcache': 'true',
                                     'smartpartition': 'true',
                                     'thin_provisioning_support': 'true',
                                     'thick_provisioning_support': 'false',
                                     'policy': '2',
                                     'cachename': 'cache-test',
                                     'partitionname': 'partition-test'})
    def test_create_smartx(self, mock_volume_types, mock_add_lun_to_partition):
        lun_info = self.driver.create_volume(self.volume)
        expect_value = {"huawei_lun_id": "1",
                        "huawei_lun_wwn": "6643e8c1004c5f6723e9f454003"}
        self.assertDictEqual(expect_value,
                             json.loads(lun_info['provider_location']))

    @ddt.data({'capabilities:smartcache': 'true',
               'cachename': 'fake_name'},
              {'capabilities:smartcache': '<is> true',
               'cachename': None},
              {'capabilities:smartcache': '<is> true',
               'cachename': ''},
              )
    def test_create_smartCache_failed(self, extra_specs):
        self.volume.volume_type = objects.VolumeType(extra_specs=extra_specs)
        self.assertRaises(exception.InvalidInput,
                          self.driver.create_volume, self.volume)

    @ddt.data(FAKE_POOLS_UNSUPPORT_REPORT, FAKE_POOLS_SUPPORT_REPORT)
    @mock.patch.object(huawei_utils, 'get_volume_params',
                       return_value={'smarttier': 'true',
                                     'smartcache': 'true',
                                     'smartpartition': 'true',
                                     'thin_provisioning_support': 'true',
                                     'thick_provisioning_support': 'false',
                                     'policy': '2',
                                     'cachename': 'cache-test',
                                     'partitionname': 'partition-test'})
    def test_create_smartCache_failed_with_no_cacheid(self,
                                                      mock_volume_type,
                                                      pool_data):
        self.driver.client.cache_not_exist = True
        self.driver.support_func = pool_data
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume, self.volume)

    @ddt.data(FAKE_POOLS_UNSUPPORT_REPORT, FAKE_POOLS_SUPPORT_REPORT)
    @mock.patch.object(huawei_utils, 'get_volume_params',
                       return_value={'smarttier': 'true',
                                     'smartcache': 'true',
                                     'smartpartition': 'true',
                                     'thin_provisioning_support': 'true',
                                     'thick_provisioning_support': 'false',
                                     'policy': '2',
                                     'cachename': 'cache-test',
                                     'partitionname': 'partition-test'})
    def test_create_smartPartition_failed_with_no_partid(self,
                                                         mock_volume_type,
                                                         pool_data):
        self.driver.client.partition_not_exist = True
        self.driver.support_func = pool_data
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume, self.volume)

    def test_find_available_qos(self):

        qos = {'MAXIOPS': '100', 'IOType': '2'}
        fake_qos_info_response_equal = {
            "error": {
                "code": 0
            },
            "data": [{
                "ID": "11",
                "MAXIOPS": "100",
                "LATENCY": "0",
                "IOType": "2",
                "FSLIST": u'[""]',
                'RUNNINGSTATUS': "2",
                "NAME": "OpenStack_57_20151225102851",
                "LUNLIST": u'["1", "2", "3", "4", "5", "6", "7", "8", "9",\
                "10", ,"11", "12", "13", "14", "15", "16", "17", "18", "19",\
                "20", ,"21", "22", "23", "24", "25", "26", "27", "28", "29",\
                "30", ,"31", "32", "33", "34", "35", "36", "37", "38", "39",\
                "40", ,"41", "42", "43", "44", "45", "46", "47", "48", "49",\
                "50", ,"51", "52", "53", "54", "55", "56", "57", "58", "59",\
                "60", ,"61", "62", "63", "64"]'
            }]
        }
        # Number of LUNs in QoS is equal to 64
        with mock.patch.object(rest_client.RestClient, 'get_qos',
                               return_value=fake_qos_info_response_equal):
            (qos_id, lun_list) = self.driver.client.find_available_qos(qos)
            self.assertEqual((None, []), (qos_id, lun_list))

        # Number of LUNs in QoS is less than 64
        fake_qos_info_response_less = {
            "error": {
                "code": 0
            },
            "data": [{
                "ID": "11",
                "MAXIOPS": "100",
                "LATENCY": "0",
                "IOType": "2",
                "FSLIST": u'[""]',
                'RUNNINGSTATUS': "2",
                "NAME": "OpenStack_57_20151225102851",
                "LUNLIST": u'["0", "1", "2"]'
            }]
        }
        with mock.patch.object(rest_client.RestClient, 'get_qos',
                               return_value=fake_qos_info_response_less):
            (qos_id, lun_list) = self.driver.client.find_available_qos(qos)
            self.assertEqual(("11", u'["0", "1", "2"]'), (qos_id, lun_list))

    @mock.patch.object(huawei_utils, 'get_volume_params',
                       return_value=fake_hypermetro_opts)
    @mock.patch.object(rest_client.RestClient, 'get_all_pools',
                       return_value=FAKE_STORAGE_POOL_RESPONSE)
    @mock.patch.object(rest_client.RestClient, 'get_pool_info',
                       return_value=FAKE_FIND_POOL_RESPONSE)
    @mock.patch.object(rest_client.RestClient, 'get_hyper_domain_id',
                       return_value='11')
    @mock.patch.object(hypermetro.HuaweiHyperMetro, '_wait_volume_ready',
                       return_value=True)
    def test_create_hypermetro_success(self,
                                       mock_volume_ready,
                                       mock_hyper_domain,
                                       mock_pool_info,
                                       mock_all_pool_info,
                                       mock_login_return):
        location = {"huawei_lun_id": "1",
                    "hypermetro_id": "11",
                    "remote_lun_id": "1",
                    "huawei_lun_wwn": "6643e8c1004c5f6723e9f454003"}
        lun_info = self.driver.create_volume(self.hyper_volume)
        self.assertDictEqual(location,
                             json.loads(lun_info['provider_location']))

    @ddt.data(FAKE_POOLS_UNSUPPORT_REPORT, FAKE_POOLS_SUPPORT_REPORT)
    @mock.patch.object(huawei_utils, 'get_volume_params',
                       return_value=fake_hypermetro_opts)
    @mock.patch.object(rest_client.RestClient, 'get_all_pools',
                       return_value=FAKE_STORAGE_POOL_RESPONSE)
    @mock.patch.object(rest_client.RestClient, 'get_pool_info',
                       return_value=FAKE_FIND_POOL_RESPONSE)
    @mock.patch.object(rest_client.RestClient, 'get_hyper_domain_id',
                       return_value='11')
    @mock.patch.object(hypermetro.HuaweiHyperMetro, '_wait_volume_ready',
                       return_value=True)
    @mock.patch.object(hypermetro.HuaweiHyperMetro,
                       '_create_hypermetro_pair')
    @mock.patch.object(rest_client.RestClient, 'delete_lun')
    def test_create_hypermetro_fail(self,
                                    pool_data,
                                    mock_delete_lun,
                                    mock_hyper_pair_info,
                                    mock_volume_ready,
                                    mock_hyper_domain,
                                    mock_pool_info,
                                    mock_all_pool_info,
                                    mock_hypermetro_opts
                                    ):
        self.driver.client.login()
        self.driver.support_func = pool_data
        mock_hyper_pair_info.side_effect = exception.VolumeBackendAPIException(
            data='Create hypermetro error.')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume, self.hyper_volume)
        mock_delete_lun.assert_called_with('1')

    @mock.patch.object(rest_client.RestClient, 'get_all_pools',
                       return_value=FAKE_STORAGE_POOL_RESPONSE)
    @mock.patch.object(rest_client.RestClient, 'get_pool_info',
                       return_value={})
    def test_create_hypermetro_remote_pool_none_fail(self,
                                                     mock_pool_info,
                                                     mock_all_pool_info):
        param = {'TYPE': '11',
                 'PARENTID': ''}
        self.driver.client.login()
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.metro.create_hypermetro,
                          '2', param)

    @mock.patch.object(rest_client.RestClient, 'get_all_pools',
                       return_value=FAKE_STORAGE_POOL_RESPONSE)
    @mock.patch.object(rest_client.RestClient, 'get_pool_info',
                       return_value=FAKE_FIND_POOL_RESPONSE)
    @mock.patch.object(rest_client.RestClient, 'create_lun',
                       return_value={'CAPACITY': '2097152',
                                     'DESCRIPTION': '2f0635',
                                     'HEALTHSTATUS': '1',
                                     'ALLOCTYPE': '1',
                                     'WWN': '6643e8c1004c5f6723e9f454003',
                                     'ID': '1',
                                     'RUNNINGSTATUS': '27',
                                     'NAME': '5mFHcBv4RkCcD'})
    @mock.patch.object(rest_client.RestClient, 'get_hyper_domain_id',
                       return_value='11')
    @mock.patch.object(hypermetro.HuaweiHyperMetro, '_wait_volume_ready',
                       return_value=True)
    def test_create_hypermetro_remote_pool_parentid(self,
                                                    mock_volume_ready,
                                                    mock_hyper_domain,
                                                    mock_create_lun,
                                                    mock_pool_info,
                                                    mock_all_pool_info):
        param = {'TYPE': '11',
                 'PARENTID': ''}
        self.driver.metro.create_hypermetro('2', param)
        lun_PARENTID = mock_create_lun.call_args[0][0]['PARENTID']
        self.assertEqual(FAKE_FIND_POOL_RESPONSE['ID'], lun_PARENTID)

    @ddt.data(FAKE_POOLS_UNSUPPORT_REPORT, FAKE_POOLS_SUPPORT_REPORT)
    @mock.patch.object(rest_client.RestClient, 'check_lun_exist',
                       return_value=True)
    @mock.patch.object(rest_client.RestClient, 'check_hypermetro_exist',
                       return_value=True)
    @mock.patch.object(rest_client.RestClient, 'delete_hypermetro',
                       return_value=FAKE_COMMON_SUCCESS_RESPONSE)
    @mock.patch.object(rest_client.RestClient, 'delete_lun',
                       return_value=None)
    def test_delete_hypermetro_success(self,
                                       mock_delete_lun,
                                       mock_delete_hypermetro,
                                       mock_check_hyermetro,
                                       mock_lun_exit,
                                       pool_data):
        self.driver.support_func = pool_data
        self.driver.delete_volume(self.hyper_volume)

    @ddt.data(FAKE_POOLS_UNSUPPORT_REPORT, FAKE_POOLS_SUPPORT_REPORT)
    @mock.patch.object(rest_client.RestClient, 'check_lun_exist',
                       return_value=True)
    @mock.patch.object(rest_client.RestClient, 'check_hypermetro_exist',
                       return_value=True)
    @mock.patch.object(rest_client.RestClient, 'get_hypermetro_by_id',
                       return_value=FAKE_METRO_INFO_RESPONSE)
    @mock.patch.object(rest_client.RestClient, 'delete_hypermetro')
    @mock.patch.object(rest_client.RestClient, 'delete_lun',
                       return_value=None)
    def test_delete_hypermetro_fail(self,
                                    pool_data,
                                    mock_delete_lun,
                                    mock_delete_hypermetro,
                                    mock_metro_info,
                                    mock_check_hyermetro,
                                    mock_lun_exit):
        self.driver.support_func = pool_data
        mock_delete_hypermetro.side_effect = (
            exception.VolumeBackendAPIException(data='Delete hypermetro '
                                                'error.'))
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_volume, self.hyper_volume)
        mock_delete_lun.assert_called_with('11')

    def test_manage_existing_get_size_invalid_reference(self):
        # Can't find LUN by source-name.
        external_ref = {'source-name': 'LUN1'}
        with mock.patch.object(rest_client.RestClient, 'get_lun_id_by_name',
                               return_value=None):
            ex = self.assertRaises(exception.ManageExistingInvalidReference,
                                   self.driver.manage_existing_get_size,
                                   self.volume, external_ref)
            self.assertIsNotNone(re.search('please check the source-name '
                                           'or source-id', ex.msg))

        # Can't find LUN by source-id.
        external_ref = {'source-id': 'ID1'}
        with mock.patch.object(rest_client.RestClient, 'get_lun_info') as m_gt:
            m_gt.side_effect = exception.VolumeBackendAPIException(
                data='Error')
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.driver.manage_existing_get_size,
                              self.volume, external_ref)
            self.assertIsNotNone(re.search('please check the source-name '
                                           'or source-id', ex.msg))

    @ddt.data({'source-id': 'ID1'}, {'source-name': 'LUN1'},
              {'source-name': 'LUN1', 'source-id': 'ID1'})
    @mock.patch.object(rest_client.RestClient, 'get_lun_info',
                       return_value={'CAPACITY': 3097152})
    @mock.patch.object(rest_client.RestClient, 'get_lun_id_by_name',
                       return_value='ID1')
    def test_manage_existing_get_size_success(self, mock_get_lun_id_by_name,
                                              mock_get_lun_info,
                                              external_ref):
        size = self.driver.manage_existing_get_size(self.volume,
                                                    external_ref)
        self.assertEqual(2, size)

    @mock.patch.object(rest_client.RestClient, 'get_lun_info',
                       return_value={'CAPACITY': 2097152,
                                     'ID': 'ID1',
                                     'PARENTNAME': 'OpenStack_Pool'})
    @mock.patch.object(rest_client.RestClient, 'get_lun_id_by_name',
                       return_value='ID1')
    def test_manage_existing_pool_mismatch(self, mock_get_by_name,
                                           mock_get_info):
        # LUN does not belong to the specified pool.
        with mock.patch.object(common.HuaweiBaseDriver,
                               '_get_lun_info_by_ref',
                               return_value={'PARENTNAME': 'StoragePool'}):
            external_ref = {'source-name': 'LUN1'}
            ex = self.assertRaises(exception.ManageExistingInvalidReference,
                                   self.driver.manage_existing,
                                   self.volume, external_ref)
            self.assertIsNotNone(re.search('The specified LUN does not belong'
                                           ' to the given pool', ex.msg))

    @mock.patch.object(rest_client.RestClient, 'get_lun_info',
                       return_value={'CAPACITY': 2097152,
                                     'ID': 'ID1',
                                     'PARENTNAME': 'OpenStack_Pool'})
    @mock.patch.object(rest_client.RestClient, 'get_lun_id_by_name',
                       return_value='ID1')
    def test_manage_existing_lun_abnormal(self, mock_get_by_name,
                                          mock_get_info):

        # Status is not normal.
        ret = {'PARENTNAME': "OpenStack_Pool",
               'HEALTHSTATUS': '2'}
        with mock.patch.object(common.HuaweiBaseDriver,
                               '_get_lun_info_by_ref',
                               return_value=ret):
            external_ref = {'source-name': 'LUN1'}
            ex = self.assertRaises(exception.ManageExistingInvalidReference,
                                   self.driver.manage_existing,
                                   self.volume, external_ref)
            self.assertIsNotNone(re.search('LUN status is not normal', ex.msg))

    @ddt.data(FAKE_POOLS_UNSUPPORT_REPORT, FAKE_POOLS_SUPPORT_REPORT)
    @mock.patch.object(rest_client.RestClient, 'get_hypermetro_pairs',
                       return_value=[{'LOCALOBJID': 'ID1'}])
    @mock.patch.object(rest_client.RestClient, 'get_lun_info',
                       return_value={'CAPACITY': 2097152,
                                     'ID': 'ID1',
                                     'PARENTNAME': 'OpenStack_Pool',
                                     'HEALTHSTATUS': constants.STATUS_HEALTH})
    @mock.patch.object(rest_client.RestClient, 'get_lun_id_by_name',
                       return_value='ID1')
    def test_manage_existing_with_hypermetro(self, mock_get_by_name,
                                             mock_get_info,
                                             mock_get_hyper_pairs,
                                             pool_data):
        self.driver.support_func = pool_data
        # Exists in a HyperMetroPair.
        with mock.patch.object(rest_client.RestClient,
                               'get_hypermetro_pairs',
                               return_value=[{'LOCALOBJID': 'ID1'}]):
            external_ref = {'source-name': 'LUN1'}
            ex = self.assertRaises(exception.ManageExistingInvalidReference,
                                   self.driver.manage_existing,
                                   self.volume, external_ref)
            self.assertIsNotNone(re.search('HyperMetroPair', ex.msg))

    @ddt.data(FAKE_POOLS_UNSUPPORT_REPORT, FAKE_POOLS_SUPPORT_REPORT)
    @mock.patch.object(rest_client.RestClient, 'get_hypermetro_pairs')
    @mock.patch.object(rest_client.RestClient, 'rename_lun')
    @mock.patch.object(rest_client.RestClient, 'get_lun_info',
                       return_value={'CAPACITY': 2097152,
                                     'ID': 'ID1',
                                     'PARENTNAME': 'OpenStack_Pool',
                                     'HEALTHSTATUS': constants.STATUS_HEALTH,
                                     'WWN': '6643e8c1004c5f6723e9f454003'})
    @mock.patch.object(rest_client.RestClient, 'get_lun_id_by_name',
                       return_value='ID1')
    def test_manage_existing_with_lower_version(self, pool_data,
                                                mock_get_by_name,
                                                mock_get_info, mock_rename,
                                                mock_get_hyper_pairs):
        self.driver.support_func = pool_data
        mock_get_hyper_pairs.side_effect = (
            exception.VolumeBackendAPIException(data='err'))
        external_ref = {'source-name': 'LUN1'}
        model_update = self.driver.manage_existing(self.volume,
                                                   external_ref)
        location = {"huawei_lun_wwn": "6643e8c1004c5f6723e9f454003",
                    "huawei_lun_id": "ID1"}
        self.assertDictEqual(location,
                             json.loads(model_update['provider_location']))

    @ddt.data([[{'PRILUNID': 'ID1'}], []],
              [[{'PRILUNID': 'ID2'}], ['ID1', 'ID2']])
    @mock.patch.object(rest_client.RestClient, 'get_lun_info',
                       return_value={'CAPACITY': 2097152,
                                     'ID': 'ID1',
                                     'PARENTNAME': 'OpenStack_Pool',
                                     'HEALTHSTATUS': constants.STATUS_HEALTH})
    @mock.patch.object(rest_client.RestClient, 'get_lun_id_by_name',
                       return_value='ID1')
    def test_manage_existing_with_splitmirror(self, ddt_data,
                                              mock_get_by_name,
                                              mock_get_info):
        self.driver.support_func = FAKE_POOLS_SUPPORT_REPORT
        # Exists in a SplitMirror.
        with mock.patch.object(rest_client.RestClient, 'get_split_mirrors',
                               return_value=ddt_data[0]), \
            mock.patch.object(rest_client.RestClient, 'get_target_luns',
                              return_value=ddt_data[1]):
            external_ref = {'source-name': 'LUN1'}
            ex = self.assertRaises(exception.ManageExistingInvalidReference,
                                   self.driver.manage_existing,
                                   self.volume, external_ref)

            self.assertIsNotNone(re.search('SplitMirror', ex.msg))

    @ddt.data([[{'PARENTID': 'ID1'}], FAKE_POOLS_UNSUPPORT_REPORT],
              [[{'TARGETLUNID': 'ID1'}], FAKE_POOLS_UNSUPPORT_REPORT],
              [[{'PARENTID': 'ID1'}], FAKE_POOLS_SUPPORT_REPORT],
              [[{'TARGETLUNID': 'ID1'}], FAKE_POOLS_SUPPORT_REPORT])
    @mock.patch.object(rest_client.RestClient, 'get_lun_info',
                       return_value={'CAPACITY': 2097152,
                                     'ID': 'ID1',
                                     'PARENTNAME': 'OpenStack_Pool',
                                     'HEALTHSTATUS': constants.STATUS_HEALTH})
    @mock.patch.object(rest_client.RestClient, 'get_lun_id_by_name',
                       return_value='ID1')
    @ddt.unpack
    def test_manage_existing_under_migration(self, ddt_data, pool_data,
                                             mock_get_by_name,
                                             mock_get_info):
        self.driver.support_func = pool_data
        # Exists in a migration task.
        with mock.patch.object(rest_client.RestClient, 'get_migration_task',
                               return_value=ddt_data):
            external_ref = {'source-name': 'LUN1'}
            ex = self.assertRaises(exception.ManageExistingInvalidReference,
                                   self.driver.manage_existing,
                                   self.volume, external_ref)
            self.assertIsNotNone(re.search('migration', ex.msg))

    @mock.patch.object(rest_client.RestClient, 'get_lun_info',
                       return_value={'CAPACITY': 2097152,
                                     'ID': 'ID1',
                                     'PARENTNAME': 'OpenStack_Pool',
                                     'SNAPSHOTIDS': [],
                                     'ISADD2LUNGROUP': 'true',
                                     'HEALTHSTATUS': constants.STATUS_HEALTH})
    @mock.patch.object(rest_client.RestClient, 'get_lun_id_by_name',
                       return_value='ID1')
    def test_manage_existing_with_lungroup(self, mock_get_by_name,
                                           mock_get_info):
        # Already in LUN group.

        external_ref = {'source-name': 'LUN1'}
        ex = self.assertRaises(exception.ManageExistingInvalidReference,
                               self.driver.manage_existing,
                               self.volume, external_ref)
        self.assertIsNotNone(re.search('Already exists in a LUN group',
                                       ex.msg))

    @ddt.data([{'source-name': 'LUN1'}, FAKE_POOLS_UNSUPPORT_REPORT],
              [{'source-name': 'LUN1'}, FAKE_POOLS_SUPPORT_REPORT],
              [{'source-id': 'ID1'}, FAKE_POOLS_UNSUPPORT_REPORT],
              [{'source-id': 'ID1'}, FAKE_POOLS_SUPPORT_REPORT])
    @mock.patch.object(rest_client.RestClient, 'rename_lun')
    @mock.patch.object(common.HuaweiBaseDriver,
                       '_get_lun_info_by_ref',
                       return_value={'PARENTNAME': 'OpenStack_Pool',
                                     'SNAPSHOTIDS': [],
                                     'ID': 'ID1',
                                     'HEALTHSTATUS': constants.STATUS_HEALTH,
                                     'WWN': '6643e8c1004c5f6723e9f454003'})
    @mock.patch.object(rest_client.RestClient, 'get_lun_info',
                       return_value={'CAPACITY': 2097152,
                                     'ALLOCTYPE': 1})
    @mock.patch.object(rest_client.RestClient, 'get_lun_id_by_name',
                       return_value='ID1')
    @ddt.unpack
    def test_manage_existing_success(self, mock_get_by_name, mock_get_info,
                                     mock_check_lun, mock_rename,
                                     external_ref, pool_data):
        self.driver.support_func = pool_data
        model_update = self.driver.manage_existing(self.volume,
                                                   external_ref)
        expected = {"huawei_lun_wwn": "6643e8c1004c5f6723e9f454003",
                    "huawei_lun_id": "ID1"}
        self.assertDictEqual(expected,
                             json.loads(model_update['provider_location']))

    def test_unmanage(self):
        self.driver.unmanage(self.volume)

    def test_manage_existing_snapshot_abnormal(self):
        with mock.patch.object(common.HuaweiBaseDriver,
                               '_get_snapshot_info_by_ref',
                               return_value={'HEALTHSTATUS': '2',
                                             'PARENTID': '11'}):
            external_ref = {'source-name': 'test1'}
            ex = self.assertRaises(exception.ManageExistingInvalidReference,
                                   self.driver.manage_existing_snapshot,
                                   self.snapshot, external_ref)
            self.assertIsNotNone(re.search('Snapshot status is not normal',
                                           ex.msg))

    @mock.patch.object(rest_client.RestClient, 'get_snapshot_info',
                       return_value={'ID': 'ID1',
                                     'EXPOSEDTOINITIATOR': 'true',
                                     'NAME': 'test1',
                                     'PARENTID': '11',
                                     'USERCAPACITY': 2097152,
                                     'HEALTHSTATUS': constants.STATUS_HEALTH})
    @mock.patch.object(rest_client.RestClient, 'get_snapshot_id_by_name',
                       return_value='ID1')
    def test_manage_existing_snapshot_with_lungroup(self, mock_get_by_name,
                                                    mock_get_info):
        # Already in LUN group.
        external_ref = {'source-name': 'test1'}
        ex = self.assertRaises(exception.ManageExistingInvalidReference,
                               self.driver.manage_existing_snapshot,
                               self.snapshot, external_ref)
        self.assertIsNotNone(re.search('Snapshot is exposed to initiator',
                                       ex.msg))

    @mock.patch.object(rest_client.RestClient, 'rename_snapshot')
    @mock.patch.object(common.HuaweiBaseDriver,
                       '_get_snapshot_info_by_ref',
                       return_value={'ID': 'ID1',
                                     'EXPOSEDTOINITIATOR': 'false',
                                     'NAME': 'test1',
                                     'PARENTID': '11',
                                     'USERCAPACITY': 2097152,
                                     'HEALTHSTATUS': constants.STATUS_HEALTH})
    def test_manage_existing_snapshot_success(self, mock_get_info,
                                              mock_rename):
        external_ref = {'source-name': 'test1'}
        model_update = self.driver.manage_existing_snapshot(self.snapshot,
                                                            external_ref)
        expect_value = {'provider_location': '{"huawei_snapshot_id": "ID1"}'}
        self.assertEqual(expect_value, model_update)

        external_ref = {'source-id': 'ID1'}
        model_update = self.driver.manage_existing_snapshot(self.snapshot,
                                                            external_ref)
        expect_value = {'provider_location': '{"huawei_snapshot_id": "ID1"}'}
        self.assertEqual(expect_value, model_update)

    @mock.patch.object(rest_client.RestClient, 'get_snapshot_info',
                       return_value={'ID': 'ID1',
                                     'EXPOSEDTOINITIATOR': 'false',
                                     'NAME': 'test1',
                                     'USERCAPACITY': 2097152,
                                     'PARENTID': '12',
                                     'HEALTHSTATUS': constants.STATUS_HEALTH})
    @mock.patch.object(rest_client.RestClient, 'get_snapshot_id_by_name',
                       return_value='ID1')
    def test_manage_existing_snapshot_mismatch_lun(self, mock_get_by_name,
                                                   mock_get_info):
        external_ref = {'source-name': 'test1'}
        ex = self.assertRaises(exception.ManageExistingInvalidReference,
                               self.driver.manage_existing_snapshot,
                               self.snapshot, external_ref)
        self.assertIsNotNone(re.search("Snapshot doesn't belong to volume",
                                       ex.msg))

    @mock.patch.object(rest_client.RestClient, 'get_snapshot_info',
                       return_value={'USERCAPACITY': 3097152})
    @mock.patch.object(rest_client.RestClient, 'get_snapshot_id_by_name',
                       return_value='ID1')
    def test_manage_existing_snapshot_get_size_success(self,
                                                       mock_get_id_by_name,
                                                       mock_get_info):
        external_ref = {'source-name': 'test1',
                        'source-id': 'ID1'}
        size = self.driver.manage_existing_snapshot_get_size(self.snapshot,
                                                             external_ref)
        self.assertEqual(2, size)

        external_ref = {'source-name': 'test1'}
        size = self.driver.manage_existing_snapshot_get_size(self.snapshot,
                                                             external_ref)
        self.assertEqual(2, size)

        external_ref = {'source-id': 'ID1'}
        size = self.driver.manage_existing_snapshot_get_size(self.snapshot,
                                                             external_ref)
        self.assertEqual(2, size)

    def test_unmanage_snapshot(self):
        self.driver.unmanage_snapshot(self.snapshot)

    @ddt.data(sync_replica_specs, async_replica_specs)
    def test_create_replication_success(self, mock_type):
        self.mock_object(replication.ReplicaCommonDriver, 'sync')
        self.replica_volume.volume_type = objects.VolumeType(
            extra_specs=mock_type, qos_specs_id=None)

        model_update = self.driver.create_volume(self.replica_volume)
        driver_data = {'pair_id': TEST_PAIR_ID,
                       'rmt_lun_id': '1',
                       'rmt_lun_wwn': '6643e8c1004c5f6723e9f454003'}
        self.assertDictEqual(
            driver_data, json.loads(model_update['replication_driver_data']))
        self.assertEqual('available', model_update['replication_status'])

    @ddt.data(
        [
            rest_client.RestClient,
            'get_array_info',
            mock.Mock(
                side_effect=exception.VolumeBackendAPIException(data='err')),
            FAKE_POOLS_UNSUPPORT_REPORT
        ],
        [
            rest_client.RestClient,
            'get_remote_devices',
            mock.Mock(
                side_effect=exception.VolumeBackendAPIException(data='err')),
            FAKE_POOLS_UNSUPPORT_REPORT
        ],
        [
            rest_client.RestClient,
            'get_remote_devices',
            mock.Mock(return_value={}),
            FAKE_POOLS_UNSUPPORT_REPORT
        ],
        [
            replication.ReplicaPairManager,
            'wait_volume_online',
            mock.Mock(side_effect=[
                None,
                exception.VolumeBackendAPIException(data='err')]),
            FAKE_POOLS_UNSUPPORT_REPORT
        ],
        [
            rest_client.RestClient,
            'create_pair',
            mock.Mock(
                side_effect=exception.VolumeBackendAPIException(data='err')),
            FAKE_POOLS_UNSUPPORT_REPORT
        ],
        [
            replication.ReplicaCommonDriver,
            'sync',
            mock.Mock(
                side_effect=exception.VolumeBackendAPIException(data='err')),
            FAKE_POOLS_UNSUPPORT_REPORT
        ],
        [
            rest_client.RestClient,
            'get_array_info',
            mock.Mock(
                side_effect=exception.VolumeBackendAPIException(data='err')),
            FAKE_POOLS_SUPPORT_REPORT
        ],
        [
            rest_client.RestClient,
            'get_remote_devices',
            mock.Mock(
                side_effect=exception.VolumeBackendAPIException(data='err')),
            FAKE_POOLS_SUPPORT_REPORT
        ],
        [
            rest_client.RestClient,
            'get_remote_devices',
            mock.Mock(return_value={}),
            FAKE_POOLS_SUPPORT_REPORT
        ],
        [
            replication.ReplicaPairManager,
            'wait_volume_online',
            mock.Mock(side_effect=[
                None,
                exception.VolumeBackendAPIException(data='err')]),
            FAKE_POOLS_SUPPORT_REPORT
        ],
        [
            rest_client.RestClient,
            'create_pair',
            mock.Mock(
                side_effect=exception.VolumeBackendAPIException(data='err')),
            FAKE_POOLS_SUPPORT_REPORT
        ],
        [
            replication.ReplicaCommonDriver,
            'sync',
            mock.Mock(
                side_effect=exception.VolumeBackendAPIException(data='err')),
            FAKE_POOLS_SUPPORT_REPORT
        ],
    )
    @ddt.unpack
    def test_create_replication_fail(self, mock_module, mock_func,
                                     mock_value, pool_data):
        self.driver.support_func = pool_data
        self.replica_volume.volume_type = objects.VolumeType(
            extra_specs=sync_replica_specs, qos_specs_id=None)

        self.mock_object(replication.ReplicaPairManager, '_delete_pair')
        self.mock_object(mock_module, mock_func, mock_value)
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.create_volume, self.replica_volume)

    @ddt.data(FAKE_POOLS_UNSUPPORT_REPORT, FAKE_POOLS_SUPPORT_REPORT)
    def test_delete_replication_success(self, pool_data):
        self.driver.support_func = pool_data
        self.mock_object(replication.ReplicaCommonDriver, 'split')
        self.mock_object(
            common.HuaweiBaseDriver,
            '_get_volume_type',
            return_value={'extra_specs': sync_replica_specs})
        self.driver.delete_volume(self.replica_volume)

        self.mock_object(rest_client.RestClient, 'check_lun_exist',
                         return_value=False)
        self.driver.delete_volume(self.replica_volume)

    def test_wait_volume_online(self):
        replica = FakeReplicaPairManager(self.driver.client,
                                         self.driver.replica_client,
                                         self.configuration)
        lun_info = {'ID': '11'}

        replica.wait_volume_online(self.driver.client, lun_info)

        offline_status = {'RUNNINGSTATUS': '28'}
        replica.wait_volume_online(self.driver.client, lun_info)

        with mock.patch.object(rest_client.RestClient, 'get_lun_info',
                               return_value=offline_status):
            self.assertRaises(retrying.RetryError,
                              replica.wait_volume_online,
                              self.driver.client,
                              lun_info)

    def test_wait_second_access(self):
        pair_id = '1'
        access_ro = constants.REPLICA_SECOND_RO
        access_rw = constants.REPLICA_SECOND_RW
        op = replication.PairOp(self.driver.client)
        common_driver = replication.ReplicaCommonDriver(self.configuration, op)
        self.mock_object(replication.PairOp, 'get_replica_info',
                         return_value={'SECRESACCESS': access_ro})

        common_driver.wait_second_access(pair_id, access_ro)
        self.assertRaises(retrying.RetryError,
                          common_driver.wait_second_access, pair_id, access_rw)

    def test_wait_replica_ready(self):
        normal_status = {
            'RUNNINGSTATUS': constants.REPLICA_RUNNING_STATUS_NORMAL,
            'HEALTHSTATUS': constants.REPLICA_HEALTH_STATUS_NORMAL
        }
        split_status = {
            'RUNNINGSTATUS': constants.REPLICA_RUNNING_STATUS_SPLIT,
            'HEALTHSTATUS': constants.REPLICA_HEALTH_STATUS_NORMAL
        }
        sync_status = {
            'RUNNINGSTATUS': constants.REPLICA_RUNNING_STATUS_SYNC,
            'HEALTHSTATUS': constants.REPLICA_HEALTH_STATUS_NORMAL
        }
        pair_id = '1'
        op = replication.PairOp(self.driver.client)
        common_driver = replication.ReplicaCommonDriver(self.configuration, op)
        with mock.patch.object(replication.PairOp, 'get_replica_info',
                               return_value=normal_status):
            common_driver.wait_replica_ready(pair_id)

        with mock.patch.object(
                replication.PairOp,
                'get_replica_info',
                side_effect=[sync_status, normal_status]):
            common_driver.wait_replica_ready(pair_id)

        with mock.patch.object(replication.PairOp, 'get_replica_info',
                               return_value=split_status):
            self.assertRaises(exception.VolumeBackendAPIException,
                              common_driver.wait_replica_ready, pair_id)

    def test_failover_to_current(self):
        driver = FakeISCSIStorage(configuration=self.configuration)
        driver.do_setup()
        old_client = driver.client
        old_replica_client = driver.replica_client
        old_replica = driver.replica
        secondary_id, volumes_update, __ = driver.failover_host(
            None, [self.volume], 'default', [])
        self.assertIn(driver.active_backend_id, ('', None))
        self.assertEqual(old_client, driver.client)
        self.assertEqual(old_replica_client, driver.replica_client)
        self.assertEqual(old_replica, driver.replica)
        self.assertEqual('default', secondary_id)
        self.assertEqual(0, len(volumes_update))

    def test_failover_normal_volumes(self):
        driver = FakeISCSIStorage(configuration=self.configuration)
        driver.do_setup()
        old_client = driver.client
        old_replica_client = driver.replica_client
        old_replica = driver.replica
        secondary_id, volumes_update, __ = driver.failover_host(
            None, [self.volume], REPLICA_BACKEND_ID, [])
        self.assertEqual(REPLICA_BACKEND_ID, driver.active_backend_id)
        self.assertEqual(old_client, driver.replica_client)
        self.assertEqual(old_replica_client, driver.client)
        self.assertNotEqual(old_replica, driver.replica)
        self.assertEqual(REPLICA_BACKEND_ID, secondary_id)
        self.assertEqual(1, len(volumes_update))
        v_id = volumes_update[0]['volume_id']
        v_update = volumes_update[0]['updates']
        self.assertEqual(self.volume.id, v_id)
        self.assertEqual('error', v_update['status'])
        self.assertEqual(self.volume['status'],
                         v_update['metadata']['old_status'])

    def test_failback_to_current(self):
        driver = FakeISCSIStorage(configuration=self.configuration)
        driver.active_backend_id = REPLICA_BACKEND_ID
        driver.do_setup()
        old_client = driver.client
        old_replica_client = driver.replica_client
        old_replica = driver.replica
        secondary_id, volumes_update, __ = driver.failover_host(
            None, [self.volume], REPLICA_BACKEND_ID, [])
        self.assertEqual(REPLICA_BACKEND_ID, driver.active_backend_id)
        self.assertEqual(old_client, driver.client)
        self.assertEqual(old_replica_client, driver.replica_client)
        self.assertEqual(old_replica, driver.replica)
        self.assertEqual(REPLICA_BACKEND_ID, secondary_id)
        self.assertEqual(0, len(volumes_update))

    def test_failback_normal_volumes(self):
        self.volume.status = 'error'
        self.volume.metadata = {'old_status': 'available'}

        driver = FakeISCSIStorage(configuration=self.configuration)
        driver.active_backend_id = REPLICA_BACKEND_ID
        driver.do_setup()
        old_client = driver.client
        old_replica_client = driver.replica_client
        old_replica = driver.replica
        secondary_id, volumes_update, __ = driver.failover_host(
            None, [self.volume], 'default', [])
        self.assertIn(driver.active_backend_id, ('', None))
        self.assertEqual(old_client, driver.replica_client)
        self.assertEqual(old_replica_client, driver.client)
        self.assertNotEqual(old_replica, driver.replica)
        self.assertEqual('default', secondary_id)
        self.assertEqual(1, len(volumes_update))
        v_id = volumes_update[0]['volume_id']
        v_update = volumes_update[0]['updates']
        self.assertEqual(self.volume.id, v_id)
        self.assertEqual('available', v_update['status'])
        self.assertNotIn('old_status', v_update['metadata'])

    def test_failover_replica_volumes(self):
        driver = FakeISCSIStorage(configuration=self.configuration)
        driver.do_setup()
        old_client = driver.client
        old_replica_client = driver.replica_client
        old_replica = driver.replica
        self.mock_object(replication.ReplicaCommonDriver, 'failover')
        self.mock_object(huawei_utils, 'get_volume_params',
                         return_value={'replication_enabled': True})
        secondary_id, volumes_update, __ = driver.failover_host(
            None, [self.replica_volume], REPLICA_BACKEND_ID, [])
        self.assertEqual(REPLICA_BACKEND_ID, driver.active_backend_id)
        self.assertEqual(old_client, driver.replica_client)
        self.assertEqual(old_replica_client, driver.client)
        self.assertNotEqual(old_replica, driver.replica)
        self.assertEqual(REPLICA_BACKEND_ID, secondary_id)
        self.assertEqual(1, len(volumes_update))
        v_id = volumes_update[0]['volume_id']
        v_update = volumes_update[0]['updates']
        self.assertEqual(self.replica_volume.id, v_id)

        expect_location = {"huawei_lun_wwn": "FAKE_RMT_LUN_WWN",
                           "huawei_lun_id": "1"}
        self.assertDictEqual(
            expect_location, json.loads(v_update['provider_location']))
        self.assertEqual('failed-over', v_update['replication_status'])

        metadata = huawei_utils.get_volume_metadata(self.replica_volume)
        new_drv_data = {'pair_id': TEST_PAIR_ID,
                        'rmt_lun_id': metadata['huawei_lun_id'],
                        'rmt_lun_wwn': metadata['huawei_lun_wwn']}
        self.assertDictEqual(
            new_drv_data, json.loads(v_update['replication_driver_data']))

    @ddt.data({}, {'pair_id': TEST_PAIR_ID})
    def test_failover_replica_volumes_invalid_drv_data(self, mock_drv_data):
        volume = self.replica_volume
        volume['replication_driver_data'] = replication.to_string(
            mock_drv_data)
        driver = FakeISCSIStorage(configuration=self.configuration)
        driver.do_setup()
        old_client = driver.client
        old_replica_client = driver.replica_client
        old_replica = driver.replica
        self.mock_object(huawei_utils, 'get_volume_params',
                         return_value={'replication_enabled': True})
        secondary_id, volumes_update, __ = driver.failover_host(
            None, [volume], REPLICA_BACKEND_ID, [])
        self.assertEqual(driver.active_backend_id, REPLICA_BACKEND_ID)
        self.assertEqual(old_client, driver.replica_client)
        self.assertEqual(old_replica_client, driver.client)
        self.assertNotEqual(old_replica, driver.replica)
        self.assertEqual(REPLICA_BACKEND_ID, secondary_id)
        self.assertEqual(1, len(volumes_update))
        v_id = volumes_update[0]['volume_id']
        v_update = volumes_update[0]['updates']
        self.assertEqual(volume.id, v_id)
        self.assertEqual('error', v_update['replication_status'])

    def test_failback_replica_volumes(self):
        self.mock_object(replication.ReplicaCommonDriver, 'enable')
        self.mock_object(replication.ReplicaCommonDriver, 'wait_replica_ready')
        self.mock_object(replication.ReplicaCommonDriver, 'failover')
        self.mock_object(huawei_utils, 'get_volume_params',
                         return_value={'replication_enabled': True})

        volume = self.replica_volume

        driver = FakeISCSIStorage(configuration=self.configuration)
        driver.active_backend_id = REPLICA_BACKEND_ID
        driver.do_setup()
        old_client = driver.client
        old_replica_client = driver.replica_client
        old_replica = driver.replica
        secondary_id, volumes_update, __ = driver.failover_host(
            None, [volume], 'default', [])
        self.assertIn(driver.active_backend_id, ('', None))
        self.assertEqual(old_client, driver.replica_client)
        self.assertEqual(old_replica_client, driver.client)
        self.assertNotEqual(old_replica, driver.replica)
        self.assertEqual('default', secondary_id)
        self.assertEqual(1, len(volumes_update))
        v_id = volumes_update[0]['volume_id']
        v_update = volumes_update[0]['updates']
        self.assertEqual(self.replica_volume.id, v_id)

        expect_location = {"huawei_lun_wwn": "FAKE_RMT_LUN_WWN",
                           "huawei_lun_id": "1"}
        self.assertDictEqual(
            expect_location, json.loads(v_update['provider_location']))
        self.assertEqual('available', v_update['replication_status'])

        metadata = huawei_utils.get_volume_metadata(self.replica_volume)
        new_drv_data = {'pair_id': TEST_PAIR_ID,
                        'rmt_lun_id': metadata['huawei_lun_id'],
                        'rmt_lun_wwn': metadata['huawei_lun_wwn']}
        self.assertDictEqual(
            new_drv_data, json.loads(v_update['replication_driver_data']))

    @ddt.data({}, {'pair_id': TEST_PAIR_ID})
    def test_failback_replica_volumes_invalid_drv_data(self, mock_drv_data):
        self.mock_object(huawei_utils, 'get_volume_params',
                         return_value={'replication_enabled': True})

        volume = self.replica_volume
        volume['replication_driver_data'] = replication.to_string(
            mock_drv_data)

        driver = FakeISCSIStorage(configuration=self.configuration)
        driver.active_backend_id = REPLICA_BACKEND_ID
        driver.do_setup()
        old_client = driver.client
        old_replica_client = driver.replica_client
        old_replica = driver.replica
        secondary_id, volumes_update, __ = driver.failover_host(
            None, [volume], 'default', [])
        self.assertIn(driver.active_backend_id, ('', None))
        self.assertEqual(old_client, driver.replica_client)
        self.assertEqual(old_replica_client, driver.client)
        self.assertNotEqual(old_replica, driver.replica)
        self.assertEqual('default', secondary_id)
        self.assertEqual(1, len(volumes_update))
        v_id = volumes_update[0]['volume_id']
        v_update = volumes_update[0]['updates']
        self.assertEqual(self.replica_volume.id, v_id)
        self.assertEqual('error', v_update['replication_status'])

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new=utils.ZeroIntervalLoopingCall)
    @mock.patch.object(replication.PairOp, 'is_primary',
                       side_effect=[False, True])
    @mock.patch.object(replication.ReplicaCommonDriver, 'split')
    @mock.patch.object(replication.ReplicaCommonDriver, 'unprotect_second')
    def test_replication_driver_enable_success(self,
                                               mock_unprotect,
                                               mock_split,
                                               mock_is_primary):
        replica_id = TEST_PAIR_ID
        op = replication.PairOp(self.driver.client)
        common_driver = replication.ReplicaCommonDriver(self.configuration, op)
        common_driver.enable(replica_id)
        self.assertTrue(mock_unprotect.called)
        self.assertTrue(mock_split.called)
        self.assertTrue(mock_is_primary.called)

    @mock.patch.object(replication.PairOp, 'is_primary', return_value=False)
    @mock.patch.object(replication.ReplicaCommonDriver, 'split')
    def test_replication_driver_failover_success(self,
                                                 mock_split,
                                                 mock_is_primary):
        replica_id = TEST_PAIR_ID
        op = replication.PairOp(self.driver.client)
        common_driver = replication.ReplicaCommonDriver(self.configuration, op)
        common_driver.failover(replica_id)
        self.assertTrue(mock_split.called)
        self.assertTrue(mock_is_primary.called)

    @mock.patch.object(replication.PairOp, 'is_primary', return_value=True)
    def test_replication_driver_failover_fail(self, mock_is_primary):
        replica_id = TEST_PAIR_ID
        op = replication.PairOp(self.driver.client)
        common_driver = replication.ReplicaCommonDriver(self.configuration, op)
        self.assertRaises(
            exception.VolumeBackendAPIException,
            common_driver.failover,
            replica_id)

    @ddt.data(constants.REPLICA_SECOND_RW, constants.REPLICA_SECOND_RO)
    def test_replication_driver_protect_second(self, mock_access):
        replica_id = TEST_PAIR_ID
        op = replication.PairOp(self.driver.client)
        common_driver = replication.ReplicaCommonDriver(self.configuration, op)

        self.mock_object(replication.ReplicaCommonDriver, 'wait_second_access')
        self.mock_object(
            replication.PairOp,
            'get_replica_info',
            return_value={'SECRESACCESS': mock_access})

        common_driver.protect_second(replica_id)
        common_driver.unprotect_second(replica_id)

    def test_replication_driver_sync(self):
        replica_id = TEST_PAIR_ID
        op = replication.PairOp(self.driver.client)
        common_driver = replication.ReplicaCommonDriver(self.configuration, op)
        async_normal_status = {
            'REPLICATIONMODEL': constants.REPLICA_ASYNC_MODEL,
            'RUNNINGSTATUS': constants.REPLICA_RUNNING_STATUS_NORMAL,
            'HEALTHSTATUS': constants.REPLICA_HEALTH_STATUS_NORMAL
        }

        self.mock_object(replication.ReplicaCommonDriver, 'protect_second')
        self.mock_object(replication.PairOp, 'get_replica_info',
                         return_value=async_normal_status)
        common_driver.sync(replica_id, True)
        common_driver.sync(replica_id, False)

    def test_replication_driver_split(self):
        replica_id = TEST_PAIR_ID
        op = replication.PairOp(self.driver.client)
        common_driver = replication.ReplicaCommonDriver(self.configuration, op)

        self.mock_object(replication.ReplicaCommonDriver, 'wait_expect_state')
        self.mock_object(
            replication.PairOp, 'split',
            side_effect=exception.VolumeBackendAPIException(data='err'))
        common_driver.split(replica_id)

    @mock.patch.object(replication.PairOp, 'split')
    @ddt.data(constants.REPLICA_RUNNING_STATUS_SPLIT,
              constants.REPLICA_RUNNING_STATUS_INVALID,
              constants.REPLICA_RUNNING_STATUS_ERRUPTED)
    def test_replication_driver_split_already_disabled(self, mock_status,
                                                       mock_op_split):
        replica_id = TEST_PAIR_ID
        op = replication.PairOp(self.driver.client)
        common_driver = replication.ReplicaCommonDriver(self.configuration, op)

        pair_info = json.loads(FAKE_GET_PAIR_NORMAL_RESPONSE)['data']
        pair_info['RUNNINGSTATUS'] = mock_status
        self.mock_object(rest_client.RestClient, 'get_pair_by_id',
                         return_value=pair_info)
        common_driver.split(replica_id)
        self.assertFalse(mock_op_split.called)

    def test_replication_base_op(self):
        replica_id = '1'
        op = replication.AbsReplicaOp(None)
        op.create()
        op.delete(replica_id)
        op.protect_second(replica_id)
        op.unprotect_second(replica_id)
        op.sync(replica_id)
        op.split(replica_id)
        op.switch(replica_id)
        op.is_primary({})
        op.get_replica_info(replica_id)
        op._is_status(None, {'key': 'volue'}, None)

    @mock.patch.object(rest_client.RestClient, 'call',
                       return_value={"error": {"code": 0}})
    def test_get_tgt_port_group_no_portg_exist(self, mock_call):
        portg = self.driver.client.get_tgt_port_group('test_portg')
        self.assertIsNone(portg)

    def test_get_tgt_iqn_from_rest_match(self):
        match_res = {
            'data': [{
                'TYPE': 249,
                'ID': '0+iqn.2006-08.com: 210048cee9d: 111.111.111.19,t,0x01'
            }, {
                'TYPE': 249,
                'ID': '0+iqn.2006-08.com: 210048cee9d: 111.111.111.191,t,0x01'
            }],
            'error': {
                'code': 0
            }
        }
        ip = '111.111.111.19'
        expected_iqn = 'iqn.2006-08.com: 210048cee9d: 111.111.111.19'
        self.mock_object(rest_client.RestClient, 'call',
                         return_value=match_res)
        iqn = self.driver.client._get_tgt_iqn_from_rest(ip)
        self.assertEqual(expected_iqn, iqn)

    def test_get_tgt_iqn_from_rest_mismatch(self):
        match_res = {
            'data': [{
                'TYPE': 249,
                'ID': '0+iqn.2006-08.com: 210048cee9d: 192.0.2.191,t,0x01'
            }, {
                'TYPE': 249,
                'ID': '0+iqn.2006-08.com: 210048cee9d: 192.0.2.192,t,0x01'
            }],
            'error': {
                'code': 0
            }
        }
        ip = '192.0.2.19'
        self.mock_object(rest_client.RestClient, 'call',
                         return_value=match_res)
        iqn = self.driver.client._get_tgt_iqn_from_rest(ip)
        self.assertIsNone(iqn)

    def test_create_group_snapshot(self):
        test_snapshots = [self.snapshot]
        ctxt = context.get_admin_context()
        self.mock_object(volume_utils, 'is_group_a_cg_snapshot_type',
                         return_value=True)
        model, snapshots = self.driver.create_group_snapshot(
            ctxt, self.group_snapshot, test_snapshots)

        self.assertEqual('21ec7341-9256-497b-97d9-ef48edcf0635',
                         snapshots[0]['id'])
        self.assertEqual('available', snapshots[0]['status'])
        self.assertDictEqual(
            {'huawei_snapshot_id': '11', 'huawei_snapshot_wwn': 'fake-wwn'},
            json.loads(snapshots[0]['provider_location']))
        self.assertEqual(fields.GroupSnapshotStatus.AVAILABLE, model['status'])

    def test_create_group_snapshot_with_create_snapshot_fail(self):
        test_snapshots = [self.snapshot]
        ctxt = context.get_admin_context()
        self.mock_object(volume_utils, 'is_group_a_cg_snapshot_type',
                         return_value=True)
        self.mock_object(
            rest_client.RestClient, 'create_snapshot',
            side_effect=exception.VolumeBackendAPIException(data='err'))
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_group_snapshot,
                          ctxt, self.group_snapshot, test_snapshots)

    def test_create_group_snapshot_with_active_snapshot_fail(self):
        test_snapshots = [self.snapshot]
        ctxt = context.get_admin_context()
        self.mock_object(volume_utils, 'is_group_a_cg_snapshot_type',
                         return_value=True)
        self.mock_object(
            rest_client.RestClient, 'activate_snapshot',
            side_effect=exception.VolumeBackendAPIException(data='err'))
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_group_snapshot,
                          ctxt, self.group_snapshot, test_snapshots)

    def test_delete_group_snapshot(self):
        test_snapshots = [self.snapshot]
        ctxt = context.get_admin_context()
        self.mock_object(volume_utils, 'is_group_a_cg_snapshot_type',
                         return_value=True)
        self.driver.delete_group_snapshot(
            ctxt, self.group_snapshot, test_snapshots)


class FCSanLookupService(object):

    def get_device_mapping_from_network(self, initiator_list,
                                        target_list):
        return fake_fabric_mapping


@ddt.ddt
class HuaweiFCDriverTestCase(HuaweiTestBase):

    def setUp(self):
        super(HuaweiFCDriverTestCase, self).setUp()
        self.configuration = mock.Mock(spec=conf.Configuration)
        self.flags(transport_url='fake:/')
        self.huawei_conf = FakeHuaweiConf(self.configuration, 'FC')
        self.configuration.hypermetro_devices = hypermetro_devices
        driver = FakeFCStorage(configuration=self.configuration)
        self.driver = driver
        self.driver.do_setup()
        self.driver.client.login()

    def test_login_success(self):
        device_id = self.driver.client.login()
        self.assertEqual('210235G7J20000000000', device_id)

    def test_create_volume_success(self):
        lun_info = self.driver.create_volume(self.volume)
        expect_value = {"huawei_lun_id": "1",
                        "huawei_lun_wwn": "6643e8c1004c5f6723e9f454003"}
        self.assertDictEqual(expect_value,
                             json.loads(lun_info['provider_location']))

    @ddt.data(FAKE_POOLS_UNSUPPORT_REPORT, FAKE_POOLS_SUPPORT_REPORT)
    def test_delete_volume_success(self, pool_data):
        self.driver.support_func = pool_data
        self.driver.delete_volume(self.volume)

    def test_delete_snapshot_success(self):
        self.driver.delete_snapshot(self.snapshot)

    def test_create_volume_from_snapsuccess(self):
        lun_info = self.driver.create_volume_from_snapshot(self.volume,
                                                           self.snapshot)
        expect_value = {"huawei_lun_id": "1",
                        "huawei_lun_wwn": "6643e8c1004c5f6723e9f454003"}
        self.assertDictEqual(expect_value,
                             json.loads(lun_info['provider_location']))

    @mock.patch.object(huawei_driver.HuaweiFCDriver,
                       'initialize_connection',
                       return_value={"data": {'target_lun': 1}})
    def test_initialize_connection_snapshot_success(self, mock_fc_init):
        iscsi_properties = self.driver.initialize_connection_snapshot(
            self.snapshot, FakeConnector)
        volume = Volume(id=self.snapshot.id,
                        provider_location=self.snapshot.provider_location,
                        lun_type='27',
                        metadata=None)
        self.assertEqual(1, iscsi_properties['data']['target_lun'])
        mock_fc_init.assert_called_with(volume, FakeConnector)

    def test_initialize_connection_success(self):
        do_mapping_mocker = self.mock_object(
            self.driver.client, 'do_mapping',
            wraps=self.driver.client.do_mapping)
        iscsi_properties = self.driver.initialize_connection(self.volume,
                                                             FakeConnector)
        self.assertEqual(1, iscsi_properties['data']['target_lun'])
        do_mapping_mocker.assert_called_once_with(
            '11', '0', '1', None, '11', False)

    def test_initialize_connection_fail_no_online_wwns_in_host(self):
        self.mock_object(rest_client.RestClient, 'get_online_free_wwns',
                         return_value=[])
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          self.volume, FakeConnector)

    def test_initialize_connection_no_local_ini_tgt_map(self):
        self.mock_object(rest_client.RestClient, 'get_init_targ_map',
                         return_value=('', ''))
        self.mock_object(huawei_driver.HuaweiFCDriver, '_get_same_hostid',
                         return_value='')
        self.mock_object(rest_client.RestClient, 'change_hostlun_id',
                         return_value=None)
        self.mock_object(rest_client.RestClient, 'do_mapping',
                         return_value={'lun_id': '1',
                                       'view_id': '1',
                                       'aval_luns': '[1]'})

        self.driver.initialize_connection(self.hyper_volume, FakeConnector)

    def test_hypermetro_connection_success(self):
        self.mock_object(rest_client.RestClient, 'find_array_version',
                         return_value='V300R003C00')
        fc_properties = self.driver.initialize_connection(self.hyper_volume,
                                                          FakeConnector)
        self.assertEqual(1, fc_properties['data']['target_lun'])

    @mock.patch.object(huawei_driver.HuaweiFCDriver,
                       'terminate_connection')
    def test_terminate_connection_snapshot_success(self, mock_fc_term):
        self.driver.terminate_connection_snapshot(self.snapshot,
                                                  FakeConnector)
        volume = Volume(id=self.snapshot.id,
                        provider_location=self.snapshot.provider_location,
                        lun_type='27',
                        metadata=None)
        mock_fc_term.assert_called_with(volume, FakeConnector)

    def test_terminate_connection_success(self):
        self.driver.client.terminateFlag = True
        self.driver.terminate_connection(self.volume, FakeConnector)
        self.assertTrue(self.driver.client.terminateFlag)

    def test_terminate_connection_portgroup_associated(self):
        self.mock_object(rest_client.RestClient,
                         'is_portgroup_associated_to_view',
                         return_value=True)
        self.mock_object(huawei_driver.HuaweiFCDriver,
                         '_delete_zone_and_remove_fc_initiators',
                         return_value=({}, 1))
        self.driver.terminate_connection(self.volume, FakeConnector)

    def test_terminate_connection_fc_initiators_exist_in_host(self):
        self.mock_object(rest_client.RestClient,
                         'check_fc_initiators_exist_in_host',
                         return_value=True)
        self.driver.terminate_connection(self.volume, FakeConnector)

    def test_terminate_connection_hypermetro_in_metadata(self):
        self.driver.terminate_connection(self.hyper_volume, FakeConnector)

    def test_get_volume_status(self):
        remote_device_info = {"ARRAYTYPE": "1",
                              "HEALTHSTATUS": "1",
                              "RUNNINGSTATUS": "10"}
        self.mock_object(
            replication.ReplicaPairManager,
            'get_remote_device_by_wwn',
            return_value=remote_device_info)
        data = self.driver.get_volume_stats()
        self.assertEqual(self.driver.VERSION, data['driver_version'])
        self.assertTrue(data['pools'][0]['replication_enabled'])
        self.assertListEqual(['sync', 'async'],
                             data['pools'][0]['replication_type'])

        self.mock_object(
            replication.ReplicaPairManager,
            'get_remote_device_by_wwn',
            return_value={})
        data = self.driver.get_volume_stats()
        self.assertNotIn('replication_enabled', data['pools'][0])

        self.mock_object(
            replication.ReplicaPairManager,
            'try_get_remote_wwn',
            return_value={})
        data = self.driver.get_volume_stats()
        self.assertEqual(self.driver.VERSION, data['driver_version'])
        self.assertNotIn('replication_enabled', data['pools'][0])

    @ddt.data({'TIER0CAPACITY': '100',
               'TIER1CAPACITY': '0',
               'TIER2CAPACITY': '0',
               'disktype': 'ssd'},
              {'TIER0CAPACITY': '0',
               'TIER1CAPACITY': '100',
               'TIER2CAPACITY': '0',
               'disktype': 'sas'},
              {'TIER0CAPACITY': '0',
               'TIER1CAPACITY': '0',
               'TIER2CAPACITY': '100',
               'disktype': 'nl_sas'},
              {'TIER0CAPACITY': '100',
               'TIER1CAPACITY': '100',
               'TIER2CAPACITY': '100',
               'disktype': 'mix'},
              {'TIER0CAPACITY': '0',
               'TIER1CAPACITY': '0',
               'TIER2CAPACITY': '0',
               'disktype': ''})
    def test_get_volume_disk_type(self, disk_type_value):
        response_dict = json.loads(FAKE_STORAGE_POOL_RESPONSE)
        storage_pool_sas = copy.deepcopy(response_dict)
        storage_pool_sas['data'][0]['TIER0CAPACITY'] = (
            disk_type_value['TIER0CAPACITY'])
        storage_pool_sas['data'][0]['TIER1CAPACITY'] = (
            disk_type_value['TIER1CAPACITY'])
        storage_pool_sas['data'][0]['TIER2CAPACITY'] = (
            disk_type_value['TIER2CAPACITY'])
        driver = FakeISCSIStorage(configuration=self.configuration)
        driver.do_setup()
        driver.replica = None

        self.mock_object(rest_client.RestClient, 'get_all_pools',
                         return_value=storage_pool_sas['data'])
        data = driver.get_volume_stats()
        if disk_type_value['disktype']:
            self.assertEqual(disk_type_value['disktype'],
                             data['pools'][0]['disk_type'])
        else:
            self.assertIsNone(data['pools'][0].get('disk_type'))

    def test_get_disk_type_pool_info_none(self):
        driver = FakeISCSIStorage(configuration=self.configuration)
        driver.do_setup()
        driver.replica = None
        self.mock_object(rest_client.RestClient, 'get_pool_info',
                         return_value=None)
        data = driver.get_volume_stats()
        self.assertIsNone(data['pools'][0].get('disk_type'))

    def test_extend_volume(self):
        self.driver.extend_volume(self.volume, 3)

    def test_login_fail(self):
        self.driver.client.test_fail = True
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.client.login)

    def test_create_snapshot_fail(self):
        self.driver.client.test_fail = True
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_snapshot, self.snapshot)

    def test_create_volume_fail(self):
        self.driver.client.test_fail = True
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume, self.volume)

    def test_initialize_connection_fail(self):
        self.driver.client.test_fail = True
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          self.volume, FakeConnector)

    def test_lun_is_associated_to_lungroup(self):
        self.driver.client.associate_lun_to_lungroup('11', '11')
        result = self.driver.client._is_lun_associated_to_lungroup('11',
                                                                   '11')
        self.assertTrue(result)

    def test_lun_is_not_associated_to_lun_group(self):
        self.driver.client.associate_lun_to_lungroup('12', '12')
        self.driver.client.remove_lun_from_lungroup('12', '12')
        result = self.driver.client._is_lun_associated_to_lungroup('12',
                                                                   '12')
        self.assertFalse(result)

    @ddt.data(FAKE_POOLS_UNSUPPORT_REPORT, FAKE_POOLS_SUPPORT_REPORT)
    @mock.patch.object(rest_client, 'RestClient')
    def test_migrate_volume_success(self, mock_add_lun_to_partition,
                                    pool_data):
        # Migrate volume without new type.
        empty_dict = {}
        self.driver.support_func = pool_data
        moved, model_update = self.driver.migrate_volume(None,
                                                         self.volume,
                                                         test_host)
        self.assertTrue(moved)
        self.assertEqual(empty_dict, model_update)

    def test_migrate_volume_fail(self):
        self.driver.client.test_fail = True

        # Migrate volume without new type.
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.migrate_volume, None,
                          self.volume, test_host)

    def test_check_migration_valid(self):
        is_valid = self.driver._check_migration_valid(test_host,
                                                      self.volume)
        self.assertTrue(is_valid)
        # No pool_name in capabilities.
        invalid_host1 = {'host': 'ubuntu001@backend002#OpenStack_Pool',
                         'capabilities':
                             {'location_info': '210235G7J20000000000',
                              'allocated_capacity_gb': 0,
                              'volume_backend_name': 'HuaweiFCDriver',
                              'storage_protocol': 'FC'}}
        is_valid = self.driver._check_migration_valid(invalid_host1,
                                                      self.volume)
        self.assertFalse(is_valid)
        # location_info in capabilities is not matched.
        invalid_host2 = {'host': 'ubuntu001@backend002#OpenStack_Pool',
                         'capabilities':
                             {'location_info': '210235G7J20000000001',
                              'allocated_capacity_gb': 0,
                              'pool_name': 'OpenStack_Pool',
                              'volume_backend_name': 'HuaweiFCDriver',
                              'storage_protocol': 'FC'}}
        is_valid = self.driver._check_migration_valid(invalid_host2,
                                                      self.volume)
        self.assertFalse(is_valid)
        # storage_protocol is not match current protocol and volume status is
        # 'in-use'.
        location = ('{"huawei_lun_wwn": "6643e8c1004c5f6723e9f454003", '
                    '"huawei_lun_id": "11"}')
        volume_in_use = {'name': 'volume-21ec7341-9256-497b-97d9-ef48edcf0635',
                         'size': 2,
                         'volume_name': 'vol1',
                         'id': ID,
                         'volume_id': '21ec7341-9256-497b-97d9-ef48edcf0635',
                         'volume_attachment': 'in-use',
                         'provider_location': location}
        invalid_host2 = {'host': 'ubuntu001@backend002#OpenStack_Pool',
                         'capabilities':
                             {'location_info': '210235G7J20000000001',
                              'allocated_capacity_gb': 0,
                              'pool_name': 'OpenStack_Pool',
                              'volume_backend_name': 'HuaweiFCDriver',
                              'storage_protocol': 'iSCSI'}}
        is_valid = self.driver._check_migration_valid(invalid_host2,
                                                      volume_in_use)
        self.assertFalse(is_valid)
        # pool_name is empty.
        invalid_host3 = {'host': 'ubuntu001@backend002#OpenStack_Pool',
                         'capabilities':
                             {'location_info': '210235G7J20000000001',
                              'allocated_capacity_gb': 0,
                              'pool_name': '',
                              'volume_backend_name': 'HuaweiFCDriver',
                              'storage_protocol': 'iSCSI'}}
        is_valid = self.driver._check_migration_valid(invalid_host3,
                                                      self.volume)
        self.assertFalse(is_valid)

    @mock.patch.object(rest_client.RestClient, 'rename_lun')
    def test_update_migrated_volume_success(self, mock_rename_lun):
        model_update = self.driver.update_migrated_volume(
            None, self.original_volume, self.current_volume, 'available')
        self.assertIsNone(model_update['_name_id'])
        self.assertDictEqual(json.loads(PROVIDER_LOCATION),
                             json.loads(model_update['provider_location']))

    @mock.patch.object(rest_client.RestClient, 'rename_lun')
    def test_update_migrated_volume_fail(self, mock_rename_lun):
        mock_rename_lun.side_effect = exception.VolumeBackendAPIException(
            data='Error occurred.')
        model_update = self.driver.update_migrated_volume(None,
                                                          self.original_volume,
                                                          self.current_volume,
                                                          'available')
        self.assertEqual(self.current_volume.name_id,
                         model_update['_name_id'])
        self.assertDictEqual(json.loads(PROVIDER_LOCATION),
                             json.loads(model_update['provider_location']))

    @mock.patch.object(rest_client.RestClient, 'add_lun_to_partition')
    def test_retype_volume_success(self, mock_add_lun_to_partition):
        self.driver.support_func = FAKE_POOLS_SUPPORT_REPORT
        retype = self.driver.retype(None, self.volume,
                                    test_new_type, None, test_host)
        self.assertTrue(retype[0])

    @ddt.data(FAKE_POOLS_UNSUPPORT_REPORT, FAKE_POOLS_SUPPORT_REPORT)
    @mock.patch.object(rest_client, 'RestClient')
    @mock.patch.object(
        common.HuaweiBaseDriver,
        '_get_volume_type',
        return_value={'extra_specs': sync_replica_specs})
    def test_retype_replication_volume_success(self, mock_get_type,
                                               mock_add_lun_to_partition,
                                               pool_data):
        self.driver.support_func = pool_data
        retype = self.driver.retype(None, self.volume,
                                    test_new_replication_type, None, test_host)
        self.assertTrue(retype[0])

    @ddt.data(
        [
            replication.ReplicaPairManager,
            'create_replica',
            exception.VolumeBackendAPIException(
                data='Can\'t support smarttier on the array.'),
            FAKE_POOLS_UNSUPPORT_REPORT
        ],
        [
            replication.ReplicaPairManager,
            'create_replica',
            exception.VolumeBackendAPIException(
                data='Can\'t support smarttier on the array.'),
            FAKE_POOLS_SUPPORT_REPORT
        ],
        [
            replication.ReplicaPairManager,
            'delete_replica',
            exception.VolumeBackendAPIException(
                data='Can\'t support smarttier on the array.'),
            FAKE_POOLS_SUPPORT_REPORT
        ],
        [
            replication.ReplicaPairManager,
            'delete_replica',
            exception.VolumeBackendAPIException(
                data='Can\'t support smarttier on the array.'),
            FAKE_POOLS_UNSUPPORT_REPORT
        ],
    )
    @ddt.unpack
    def test_retype_replication_volume_fail(self,
                                            mock_module,
                                            mock_func,
                                            side_effect,
                                            pool_data):
        self.driver.support_func = pool_data
        self.mock_object(mock_module, mock_func, side_effect=side_effect)
        self.mock_object(rest_client.RestClient, 'add_lun_to_partition')

        if mock_func == 'create_replica':
            extra_specs = {}
            new_type = test_new_replication_type
        else:
            extra_specs = {'capabilities:replication_enabled': '<is> True'}
            new_type = {'extra_specs': {},
                        }

        self.volume.volume_type = objects.VolumeType(
            extra_specs=extra_specs, qos_specs_id=None)
        retype = self.driver.retype(None, self.volume,
                                    new_type, None, test_host)
        self.assertFalse(retype)

    @ddt.data(FAKE_POOLS_UNSUPPORT_REPORT, FAKE_POOLS_SUPPORT_REPORT)
    def test_retype_volume_cache_fail(self, pool_data):
        self.driver.client.cache_not_exist = True
        self.driver.support_func = pool_data

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.retype, None,
                          self.volume, test_new_type, None, test_host)

    @ddt.data(FAKE_POOLS_UNSUPPORT_REPORT, FAKE_POOLS_SUPPORT_REPORT)
    def test_retype_volume_partition_fail(self, pool_data):
        self.driver.support_func = pool_data
        self.driver.client.partition_not_exist = True

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.retype, None,
                          self.volume, test_new_type, None, test_host)

    @mock.patch.object(rest_client.RestClient, 'add_lun_to_partition')
    def test_retype_volume_fail(self, mock_add_lun_to_partition):
        self.driver.support_func = FAKE_POOLS_SUPPORT_REPORT
        mock_add_lun_to_partition.side_effect = (
            exception.VolumeBackendAPIException(data='Error occurred.'))
        retype = self.driver.retype(None, self.volume,
                                    test_new_type, None, test_host)
        self.assertFalse(retype)

    @mock.patch.object(rest_client.RestClient, 'get_all_engines',
                       return_value=[{'NODELIST': '["0A","0B"]', 'ID': '0'}])
    def test_build_ini_targ_map_engie_recorded(self, mock_engines):
        fake_lookup_service = FCSanLookupService()

        zone_helper = fc_zone_helper.FCZoneHelper(
            fake_lookup_service, self.driver.client)
        (tgt_wwns, portg_id, init_targ_map) = zone_helper.build_ini_targ_map(
            ['10000090fa0d6754'], '1', '11')
        target_port_wwns = ['2000643e8c4c5f66']
        self.assertEqual(target_port_wwns, tgt_wwns)
        self.assertEqual({}, init_targ_map)

    @ddt.data(fake_fabric_mapping_no_ports, fake_fabric_mapping_no_wwn)
    def test_filter_by_fabric_fail(self, ddt_map):
        self.mock_object(
            FCSanLookupService, 'get_device_mapping_from_network',
            return_value=ddt_map)
        fake_lookup_service = FCSanLookupService()
        zone_helper = fc_zone_helper.FCZoneHelper(
            fake_lookup_service, self.driver.client)
        self.assertRaises(exception.VolumeBackendAPIException,
                          zone_helper._filter_by_fabric, ['10000090fa0d6754'],
                          None)

    @mock.patch.object(rest_client.RestClient, 'get_all_engines',
                       return_value=[{'NODELIST': '["0A"]', 'ID': '0'},
                                     {'NODELIST': '["0B"]', 'ID': '1'}])
    @mock.patch.object(fc_zone_helper.FCZoneHelper, '_build_contr_port_map',
                       return_value={'0B': ['2000643e8c4c5f67']})
    def test_build_ini_targ_map_engie_not_recorded(self, mock_engines, map):
        fake_lookup_service = FCSanLookupService()

        zone_helper = fc_zone_helper.FCZoneHelper(
            fake_lookup_service, self.driver.client)
        (tgt_wwns, portg_id, init_targ_map) = zone_helper.build_ini_targ_map(
            ['10000090fa0d6754'], '1', '11')
        expected_wwns = ['2000643e8c4c5f67', '2000643e8c4c5f66']
        expected_map = {'10000090fa0d6754': expected_wwns}
        self.assertEqual(expected_wwns, tgt_wwns)
        self.assertEqual(expected_map, init_targ_map)

    @mock.patch.object(rest_client.RestClient, 'get_all_engines',
                       return_value=[{'NODELIST': '["0A", "0B"]', 'ID': '0'}])
    def test_build_ini_targ_map_no_map(self, mock_engines):
        fake_lookup_service = FCSanLookupService()

        zone_helper = fc_zone_helper.FCZoneHelper(
            fake_lookup_service, self.driver.client)
        # Host with id '5' has no map on the array.
        (tgt_wwns, portg_id, init_targ_map) = zone_helper.build_ini_targ_map(
            ['10000090fa0d6754'], '5', '11')
        expected_wwns = ['2000643e8c4c5f66']
        expected_map = {'10000090fa0d6754': ['2000643e8c4c5f66']}
        self.assertEqual(expected_wwns, tgt_wwns)
        self.assertEqual(expected_map, init_targ_map)

    @mock.patch.object(rest_client.RestClient, 'get_all_engines',
                       return_value=[{'NODELIST': '["0A", "0B"]', 'ID': '0'}])
    @mock.patch.object(rest_client.RestClient, 'get_tgt_port_group',
                       return_value='0')
    @mock.patch.object(rest_client.RestClient, 'delete_portgroup')
    def test_build_ini_targ_map_exist_portg(self, delete, engines, portg):
        fake_lookup_service = FCSanLookupService()

        zone_helper = fc_zone_helper.FCZoneHelper(
            fake_lookup_service, self.driver.client)
        # Host with id '5' has no map on the array.
        (tgt_wwns, portg_id, init_targ_map) = zone_helper.build_ini_targ_map(
            ['10000090fa0d6754'], '5', '11')
        expected_wwns = ['2000643e8c4c5f66']
        expected_map = {'10000090fa0d6754': ['2000643e8c4c5f66']}
        self.assertEqual(expected_wwns, tgt_wwns)
        self.assertEqual(expected_map, init_targ_map)
        self.assertEqual(1, delete.call_count)

    def test_get_init_targ_map(self):
        fake_lookup_service = FCSanLookupService()

        zone_helper = fc_zone_helper.FCZoneHelper(
            fake_lookup_service, self.driver.client)
        (tgt_wwns, portg_id, init_targ_map) = zone_helper.get_init_targ_map(
            ['10000090fa0d6754'], '1')
        expected_wwns = ['2000643e8c4c5f66']
        expected_map = {'10000090fa0d6754': ['2000643e8c4c5f66']}
        self.assertEqual(expected_wwns, tgt_wwns)
        self.assertEqual(expected_map, init_targ_map)

    def test_get_init_targ_map_no_host(self):
        fake_lookup_service = FCSanLookupService()

        zone_helper = fc_zone_helper.FCZoneHelper(
            fake_lookup_service, self.driver.client)
        ret = zone_helper.get_init_targ_map(
            ['10000090fa0d6754'], None)
        expected_ret = ([], None, {})
        self.assertEqual(expected_ret, ret)

    def test_multi_resturls_success(self):
        self.driver.client.test_multi_url_flag = True
        lun_info = self.driver.create_volume(self.volume)
        expect_value = {"huawei_lun_id": "1",
                        "huawei_lun_wwn": "6643e8c1004c5f6723e9f454003"}
        self.assertDictEqual(expect_value,
                             json.loads(lun_info['provider_location']))

    def test_get_id_from_result(self):
        result = {}
        name = 'test_name'
        key = 'NAME'
        re = self.driver.client._get_id_from_result(result, name, key)
        self.assertIsNone(re)

        result = {'data': {}}
        re = self.driver.client._get_id_from_result(result, name, key)
        self.assertIsNone(re)

        result = {'data': [{'COUNT': 1, 'ID': '1'},
                           {'COUNT': 2, 'ID': '2'}]}

        re = self.driver.client._get_id_from_result(result, name, key)
        self.assertIsNone(re)

        result = {'data': [{'NAME': 'test_name1', 'ID': '1'},
                           {'NAME': 'test_name2', 'ID': '2'}]}
        re = self.driver.client._get_id_from_result(result, name, key)
        self.assertIsNone(re)

        result = {'data': [{'NAME': 'test_name', 'ID': '1'},
                           {'NAME': 'test_name2', 'ID': '2'}]}
        re = self.driver.client._get_id_from_result(result, name, key)
        self.assertEqual('1', re)

    @mock.patch.object(rest_client.RestClient, 'get_pool_info',
                       return_value={'ID': 1,
                                     'CAPACITY': 110362624,
                                     'TOTALCAPACITY': 209715200})
    def test_get_capacity(self, mock_get_pool_info):
        expected_pool_capacity = {'total_capacity': 100.0,
                                  'free_capacity': 52.625}
        pool_capacity = self.driver.client._get_capacity(None,
                                                         None)
        self.assertEqual(expected_pool_capacity, pool_capacity)

    @mock.patch.object(huawei_utils, 'get_volume_params',
                       return_value=fake_hypermetro_opts)
    @mock.patch.object(rest_client.RestClient, 'get_all_pools',
                       return_value=FAKE_STORAGE_POOL_RESPONSE)
    @mock.patch.object(rest_client.RestClient, 'get_pool_info',
                       return_value=FAKE_FIND_POOL_RESPONSE)
    @mock.patch.object(rest_client.RestClient, 'get_hyper_domain_id',
                       return_value='11')
    @mock.patch.object(hypermetro.HuaweiHyperMetro, '_wait_volume_ready',
                       return_value=True)
    @mock.patch.object(hypermetro.HuaweiHyperMetro,
                       '_create_hypermetro_pair',
                       return_value={"ID": '11',
                                     "NAME": 'hypermetro-pair'})
    @mock.patch.object(rest_client.RestClient, 'logout',
                       return_value=None)
    def test_create_hypermetro_success(self, mock_hypermetro_opts,
                                       mock_login_return,
                                       mock_all_pool_info,
                                       mock_pool_info,
                                       mock_hyper_domain,
                                       mock_volume_ready,
                                       mock_logout):

        location = {"huawei_lun_id": "1",
                    "hypermetro_id": "11",
                    "remote_lun_id": "1",
                    "huawei_lun_wwn": "6643e8c1004c5f6723e9f454003"}
        lun_info = self.driver.create_volume(self.hyper_volume)
        self.assertDictEqual(location,
                             json.loads(lun_info['provider_location']))

    @ddt.data(FAKE_POOLS_UNSUPPORT_REPORT, FAKE_POOLS_SUPPORT_REPORT)
    @mock.patch.object(huawei_utils, 'get_volume_params',
                       return_value=fake_hypermetro_opts)
    @mock.patch.object(rest_client.RestClient, 'get_all_pools',
                       return_value=FAKE_STORAGE_POOL_RESPONSE)
    @mock.patch.object(rest_client.RestClient, 'get_pool_info',
                       return_value=FAKE_FIND_POOL_RESPONSE)
    @mock.patch.object(rest_client.RestClient, 'get_hyper_domain_id',
                       return_value='11')
    @mock.patch.object(hypermetro.HuaweiHyperMetro, '_wait_volume_ready',
                       return_value=True)
    @mock.patch.object(rest_client.RestClient, 'create_hypermetro')
    def test_create_hypermetro_fail(self,
                                    pool_data,
                                    mock_pair_info,
                                    mock_hypermetro_opts,
                                    mock_all_pool_info,
                                    mock_pool_info,
                                    mock_hyper_domain,
                                    mock_volume_ready
                                    ):
        self.driver.support_func = pool_data
        mock_pair_info.side_effect = (
            exception.VolumeBackendAPIException(data='Error occurred.'))
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.metro.create_hypermetro, "11", {})

    @mock.patch.object(huawei_utils, 'get_volume_private_data',
                       return_value={'hypermetro_id': '3400a30d844d0007',
                                     'remote_lun_id': '1'})
    @mock.patch.object(rest_client.RestClient, 'do_mapping',
                       return_value={'lun_id': '1',
                                     'view_id': '1',
                                     'aval_luns': '[1]'})
    def test_hypermetro_connection_success_2(self, mock_map, mock_metadata):
        fc_properties = self.driver.metro.connect_volume_fc(self.volume,
                                                            FakeConnector)
        self.assertEqual(1, fc_properties['data']['target_lun'])
        mock_map.assert_called_once_with('1', '0', '1',
                                         hypermetro_lun=True)

    @mock.patch.object(huawei_driver.huawei_utils, 'get_volume_metadata',
                       return_value={'hypermetro_id': '3400a30d844d0007',
                                     'remote_lun_id': '1'})
    def test_terminate_hypermetro_connection_success(self, mock_metradata):
        self.driver.metro.disconnect_volume_fc(self.volume, FakeConnector)

    @mock.patch.object(huawei_utils, 'get_volume_private_data',
                       return_value={'hypermetro_id': '3400a30d844d0007',
                                     'remote_lun_id': None})
    @mock.patch.object(rest_client.RestClient, 'get_lun_id_by_name',
                       return_value=None)
    def test_hypermetroid_none_fail(self, mock_metadata, moke_metro_name):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.metro.connect_volume_fc,
                          self.hyper_volume,
                          FakeConnector)

    def test_wait_volume_ready_success(self):
        flag = self.driver.metro._wait_volume_ready("11")
        self.assertIsNone(flag)

    @mock.patch.object(huawei_driver.huawei_utils, 'get_volume_metadata',
                       return_value={'hypermetro_id': '3400a30d844d0007',
                                     'remote_lun_id': '1'})
    @mock.patch.object(rest_client.RestClient, 'get_online_free_wwns',
                       return_value=[])
    @mock.patch.object(rest_client.RestClient, 'get_host_iscsi_initiators',
                       return_value=[])
    def test_hypermetro_connection_fail(self, mock_metadata,
                                        mock_fc_initiator,
                                        mock_host_initiators):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.metro.connect_volume_fc,
                          self.hyper_volume,
                          FakeConnector)

    def test_create_snapshot_fail_hypermetro(self):
        self.volume.volume_type = objects.VolumeType(
            extra_specs=replica_hypermetro_specs, qos_specs_id=None)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          self.volume, self.snapshot)

    def test_create_snapshot_fail_no_snapshot_id(self):
        self.snapshot.provider_location = None
        self.mock_object(self.driver.client, 'get_snapshot_info_by_name',
                         return_value=None)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          self.volume, self.snapshot)

    @mock.patch.object(rest_client.RestClient, 'call',
                       return_value={"data": [{"RUNNINGSTATUS": "27",
                                               "ID": '1'},
                                              {"RUNNINGSTATUS": "26",
                                               "ID": '2'}],
                                     "error": {"code": 0}})
    def test_get_online_free_wwns(self, mock_call):
        wwns = self.driver.client.get_online_free_wwns()
        self.assertEqual(['1'], wwns)

    def test_get_fc_initiator_on_array(self):
        wwns = self.driver.client.get_fc_initiator_on_array()
        self.assertListEqual(["10000090fa0d6754", "10000090fa0d6755"], wwns)

    @mock.patch.object(rest_client.RestClient, 'call',
                       return_value={"data": {"ID": 1}, "error": {"code": 0}})
    def test_rename_lun(self, mock_call):
        des = 'This LUN is renamed.'
        new_name = 'test_name'
        self.driver.client.rename_lun('1', new_name, des)
        self.assertEqual(1, mock_call.call_count)
        url = "/lun/1"
        data = {"NAME": new_name, "DESCRIPTION": des}
        mock_call.assert_called_once_with(url, data, "PUT")

    @mock.patch.object(rest_client.RestClient, 'call',
                       return_value={"data": {}})
    def test_is_host_associated_to_hostgroup_no_data(self, mock_call):
        res = self.driver.client.is_host_associated_to_hostgroup('1')
        self.assertFalse(res)

    @mock.patch.object(rest_client.RestClient, 'call',
                       return_value={"data": {'ISADD2HOSTGROUP': 'true'}})
    def test_is_host_associated_to_hostgroup_true(self, mock_call):
        res = self.driver.client.is_host_associated_to_hostgroup('1')
        self.assertTrue(res)

    @mock.patch.object(rest_client.RestClient, 'call',
                       return_value={"data": {'ISADD2HOSTGROUP': 'false'}})
    def test_is_host_associated_to_hostgroup_false(self, mock_call):
        res = self.driver.client.is_host_associated_to_hostgroup('1')
        self.assertFalse(res)

    @ddt.data([{"hypermetro": "true"}], [])
    def test_create_group_success(self, cg_type):
        self.mock_object(common.HuaweiBaseDriver, '_get_group_type',
                         return_value=cg_type)
        self.mock_object(volume_utils, 'is_group_a_cg_snapshot_type',
                         return_value=True)
        model_update = self.driver.create_group(None, self.group)
        self.assertEqual(fields.GroupStatus.AVAILABLE, model_update['status'])

    @ddt.data(
        ([fake_snapshot.fake_snapshot_obj(
            None, provider_location=SNAP_PROVIDER_LOCATION, id=ID)],
         [], False),
        ([], [fake_volume.fake_volume_obj(
            None, provider_location=PROVIDER_LOCATION, id=ID)], True),
    )
    @ddt.unpack
    def test_create_group_from_src(self, snapshots, source_vols, tmp_snap):
        self.mock_object(common.HuaweiBaseDriver, '_get_group_type',
                         return_value=[])
        self.mock_object(volume_utils, 'is_group_a_cg_snapshot_type',
                         return_value=True)

        create_snap_mock = self.mock_object(
            self.driver, '_create_group_snapshot',
            wraps=self.driver._create_group_snapshot)
        delete_snap_mock = self.mock_object(
            self.driver, '_delete_group_snapshot',
            wraps=self.driver._delete_group_snapshot)
        self.mock_object(self.driver.client, 'get_snapshot_info_by_name',
                         return_value={'ID': ID})

        model_update, volumes_model_update = self.driver.create_group_from_src(
            None, self.group, [self.volume], snapshots=snapshots,
            source_vols=source_vols)

        if tmp_snap:
            create_snap_mock.assert_called_once()
            delete_snap_mock.assert_called_once()
        else:
            create_snap_mock.assert_not_called()
            delete_snap_mock.assert_not_called()

        self.assertDictEqual({'status': fields.GroupStatus.AVAILABLE},
                             model_update)
        self.assertEqual(1, len(volumes_model_update))
        self.assertEqual(ID, volumes_model_update[0]['id'])

    @ddt.data([{"hypermetro": "true"}], [])
    def test_delete_group_success(self, cg_type):
        test_volumes = [self.volume]
        ctxt = context.get_admin_context()
        self.mock_object(common.HuaweiBaseDriver, '_get_group_type',
                         return_value=cg_type)
        self.mock_object(volume_utils, 'is_group_a_cg_snapshot_type',
                         return_value=True)
        model, volumes = self.driver.delete_group(
            ctxt, self.group, test_volumes)
        self.assertEqual(fields.GroupStatus.DELETED, model['status'])

    @mock.patch.object(common.HuaweiBaseDriver, '_get_group_type',
                       return_value=[{"hypermetro": "true"}])
    @mock.patch.object(huawei_driver.huawei_utils, 'get_volume_metadata',
                       return_value={'hypermetro_id': '3400a30d844d0007',
                                     'remote_lun_id': '59'})
    def test_update_group_success(self, mock_grouptype, mock_metadata):
        ctxt = context.get_admin_context()
        add_volumes = [self.hyper_volume]
        remove_volumes = []
        self.mock_object(volume_utils, 'is_group_a_cg_snapshot_type',
                         return_value=True)
        model_update = self.driver.update_group(
            ctxt, self.group, add_volumes, remove_volumes)
        self.assertEqual(fields.GroupStatus.AVAILABLE,
                         model_update[0]['status'])

    def test_is_initiator_associated_to_host_raise(self):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.client.is_initiator_associated_to_host,
                          'ini-2', '1')

    def test_is_initiator_associated_to_host_true(self):
        ret = self.driver.client.is_initiator_associated_to_host('ini-1', '1')
        self.assertFalse(ret)
        ret = self.driver.client.is_initiator_associated_to_host('ini-2', '2')
        self.assertTrue(ret)


@ddt.ddt
class HuaweiConfTestCase(test.TestCase):
    def setUp(self):
        super(HuaweiConfTestCase, self).setUp()

        self.tmp_dir = tempfile.mkdtemp()
        self.fake_xml_file = self.tmp_dir + '/cinder_huawei_conf.xml'

        self.conf = mock.Mock()
        self.conf.cinder_huawei_conf_file = self.fake_xml_file
        self.huawei_conf = huawei_conf.HuaweiConf(self.conf)

    def _create_fake_conf_file(self, configs):
        """Create a fake Config file.

          Huawei storage customize a XML configuration file, the configuration
          file is used to set the Huawei storage custom parameters, therefore,
          in the UT test we need to simulate such a configuration file.
        """
        doc = minidom.Document()

        config = doc.createElement('config')
        doc.appendChild(config)

        storage = doc.createElement('Storage')
        config.appendChild(storage)
        url = doc.createElement('RestURL')
        url_text = doc.createTextNode('http://192.0.2.69:8082/'
                                      'deviceManager/rest/')
        url.appendChild(url_text)
        storage.appendChild(url)
        username = doc.createElement('UserName')
        username_text = doc.createTextNode('admin')
        username.appendChild(username_text)
        storage.appendChild(username)
        password = doc.createElement('UserPassword')
        password_text = doc.createTextNode('Admin@storage')
        password.appendChild(password_text)
        storage.appendChild(password)
        product = doc.createElement('Product')
        product_text = doc.createTextNode(configs.get('Product', 'V3'))
        product.appendChild(product_text)
        storage.appendChild(product)
        protocol = doc.createElement('Protocol')
        protocol_text = doc.createTextNode('iSCSI')
        protocol.appendChild(protocol_text)
        storage.appendChild(protocol)

        lun = doc.createElement('LUN')
        config.appendChild(lun)

        if 'LUNType' in configs:
            luntype = doc.createElement('LUNType')
            luntype_text = doc.createTextNode(configs['LUNType'])
            luntype.appendChild(luntype_text)
            lun.appendChild(luntype)

        lun_ready_wait_interval = doc.createElement('LUNReadyWaitInterval')
        lun_ready_wait_interval_text = doc.createTextNode('2')
        lun_ready_wait_interval.appendChild(lun_ready_wait_interval_text)
        lun.appendChild(lun_ready_wait_interval)
        lun_copy_wait_interval = doc.createElement('LUNcopyWaitInterval')
        lun_copy_wait_interval_text = doc.createTextNode('2')
        lun_copy_wait_interval.appendChild(lun_copy_wait_interval_text)
        lun.appendChild(lun_copy_wait_interval)
        timeout = doc.createElement('Timeout')
        timeout_text = doc.createTextNode('43200')
        timeout.appendChild(timeout_text)
        lun.appendChild(timeout)
        write_type = doc.createElement('WriteType')
        write_type_text = doc.createTextNode('1')
        write_type.appendChild(write_type_text)
        lun.appendChild(write_type)
        mirror_switch = doc.createElement('MirrorSwitch')
        mirror_switch_text = doc.createTextNode('1')
        mirror_switch.appendChild(mirror_switch_text)
        lun.appendChild(mirror_switch)
        prefetch = doc.createElement('Prefetch')
        prefetch.setAttribute('Type', '1')
        prefetch.setAttribute('Value', '0')
        lun.appendChild(prefetch)
        pool = doc.createElement('StoragePool')
        pool_text = doc.createTextNode('OpenStack_Pool')
        pool.appendChild(pool_text)
        lun.appendChild(pool)

        iscsi = doc.createElement('iSCSI')
        config.appendChild(iscsi)
        defaulttargetip = doc.createElement('DefaultTargetIP')
        defaulttargetip_text = doc.createTextNode('192.0.2.68')
        defaulttargetip.appendChild(defaulttargetip_text)
        iscsi.appendChild(defaulttargetip)
        initiator = doc.createElement('Initiator')
        initiator.setAttribute('Name', 'iqn.1993-08.debian:01:ec2bff7ac3a3')
        initiator.setAttribute('TargetIP', '192.0.2.2')
        initiator.setAttribute('CHAPinfo', 'mm-user;mm-user@storage')
        initiator.setAttribute('ALUA', '1')
        initiator.setAttribute('TargetPortGroup', 'PortGroup001')
        iscsi.appendChild(initiator)

        fakefile = open(self.conf.cinder_huawei_conf_file, 'w')
        fakefile.write(doc.toprettyxml(indent=''))
        fakefile.close()

    @ddt.data(
        (
            {
                'Product': 'Dorado',
                'LUNType': 'Thin',
            },
            1,
        ),
        (
            {
                'Product': 'Dorado',
            },
            1,
        ),
        (
            {
                'Product': 'Dorado',
                'LUNType': 'Thick',
            },
            exception.InvalidInput,
        ),
        (
            {
                'Product': 'V3',
                'LUNType': 'Thick',
            },
            0,
        ),
        (
            {
                'Product': 'V3',
                'LUNType': 'invalid',
            },
            exception.InvalidInput,
        ),
    )
    @ddt.unpack
    def test_luntype_config(self, custom_configs, expect_result):
        self._create_fake_conf_file(custom_configs)
        tree = ElementTree.parse(self.conf.cinder_huawei_conf_file)
        xml_root = tree.getroot()
        self.huawei_conf._san_product(xml_root)

        if isinstance(expect_result, int):
            self.huawei_conf._lun_type(xml_root)
            self.assertEqual(expect_result, self.conf.lun_type)
        else:
            self.assertRaises(expect_result,
                              self.huawei_conf._lun_type, xml_root)

    @ddt.data(
        [{
            'backend_id': "default",
            'san_address': 'https://192.0.2.69:8088/deviceManager/rest/',
            'san_user': 'admin',
            'san_password': '123456',
            'storage_pool': 'OpenStack_Pool',
            'iscsi_info': '{Name:iqn;CHAPinfo:user#pwd;ALUA:1}'
        }]
    )
    def test_get_replication_devices(self, config):
        self.mock_object(self.conf,
                         'safe_get',
                         mock.Mock(return_value=config)
                         )

        self.huawei_conf._replication_devices(None)
        expected = {
            'backend_id': 'default',
            'san_address': ['https://192.0.2.69:8088/deviceManager/rest/'],
            'san_password': '123456',
            'san_user': 'admin',
            'storage_pools': ['OpenStack_Pool'],
            'vstore_name': None,
            'iscsi_info': {
                'initiators': {
                    'iqn': {'ALUA': '1',
                            'CHAPinfo': 'user;pwd',
                            'Name': 'iqn'}
                },
                'default_target_ips': [],
            },
            'fc_info': {
                'initiators': {},
                'default_target_ips': [],
            },
        }

        self.assertDictEqual(expected, self.conf.replication)


@ddt.ddt
class HuaweiRestClientTestCase(test.TestCase):
    def setUp(self):
        super(HuaweiRestClientTestCase, self).setUp()
        config = mock.Mock(spec=conf.Configuration)
        huawei_conf = FakeHuaweiConf(config, 'iSCSI')
        huawei_conf.update_config_value()
        self.client = rest_client.RestClient(
            config, config.san_address, config.san_user, config.san_password)

    def test_init_http_head(self):
        self.client.init_http_head()
        self.assertIsNone(self.client.url)
        self.assertEqual("keep-alive",
                         self.client.session.headers["Connection"])
        self.assertEqual("application/json",
                         self.client.session.headers["Content-Type"])
        self.assertEqual(False, self.client.session.verify)

    @ddt.data('POST', 'PUT', 'GET', 'DELETE')
    def test_do_call_method(self, method):
        self.client.init_http_head()

        if method:
            mock_func = self.mock_object(self.client.session, method.lower())
        else:
            mock_func = self.mock_object(self.client.session, 'post')

        self.client.do_call("http://fake-rest-url", None, method)
        mock_func.assert_called_once_with("http://fake-rest-url",
                                          timeout=constants.SOCKET_TIMEOUT)

    def test_do_call_method_invalid(self):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.client.do_call,
                          "http://fake-rest-url", None, 'fake-method')

    def test_do_call_http_error(self):
        self.client.init_http_head()

        fake_res = requests.Response()
        fake_res.reason = 'something wrong'
        fake_res.status_code = 500
        fake_res.url = "http://fake-rest-url"

        self.mock_object(self.client.session, 'post', return_value=fake_res)
        res = self.client.do_call("http://fake-rest-url", None, 'POST')

        expected = {"error": {"code": 500,
                              "description":
                                  '500 Server Error: something wrong for '
                                  'url: http://fake-rest-url'}}
        self.assertEqual(expected, res)
