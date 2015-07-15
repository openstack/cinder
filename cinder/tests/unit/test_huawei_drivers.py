# Copyright (c) 2015 Huawei Technologies Co., Ltd.
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
"""Tests for huawei 18000 storage."""
import json
import mock
import os
import shutil
import tempfile
import time
from xml.dom import minidom

from oslo_log import log as logging

from cinder import exception
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.huawei import constants
from cinder.volume.drivers.huawei import fc_zone_helper
from cinder.volume.drivers.huawei import huawei_driver
from cinder.volume.drivers.huawei import huawei_utils
from cinder.volume.drivers.huawei import hypermetro
from cinder.volume.drivers.huawei import rest_client
from cinder.volume.drivers.huawei import smartx

LOG = logging.getLogger(__name__)

hypermetro_devices = """{
    "remote_device": {
        "RestURL": "http://100.115.10.69:8082/deviceManager/rest",
        "UserName": "admin",
        "UserPassword": "Admin@storage1",
        "StoragePool": "StoragePool001",
        "domain_name": "hypermetro-domain",
        "remote_target_ip": "111.111.101.241"
    }
}
"""

test_volume = {'name': 'volume-21ec7341-9256-497b-97d9-ef48edcf0635',
               'size': 2,
               'volume_name': 'vol1',
               'id': '21ec7341-9256-497b-97d9-ef48edcf0635',
               'volume_id': '21ec7341-9256-497b-97d9-ef48edcf0635',
               'provider_auth': None,
               'project_id': 'project',
               'display_name': 'vol1',
               'display_description': 'test volume',
               'volume_type_id': None,
               'host': 'ubuntu001@backend001#OpenStack_Pool',
               'provider_location': '11',
               }

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

hyper_volume = {'name': 'volume-21ec7341-9256-497b-97d9-ef48edcf0635',
                'size': 2,
                'volume_name': 'vol1',
                'id': '21ec7341-9256-497b-97d9-ef48edcf0635',
                'volume_id': '21ec7341-9256-497b-97d9-ef48edcf0635',
                'provider_auth': None,
                'project_id': 'project',
                'display_name': 'vol1',
                'display_description': 'test volume',
                'volume_type_id': None,
                'host': 'ubuntu@huawei#OpenStack_Pool',
                'provider_location': '11',
                'volume_metadata': [{'key': 'hypermetro_id',
                                     'value': '1'},
                                    {'key': 'remote_lun_id',
                                     'value': '11'}],
                }

test_snap = {'name': 'volume-21ec7341-9256-497b-97d9-ef48edcf0635',
             'size': 1,
             'volume_name': 'vol1',
             'id': '21ec7341-9256-497b-97d9-ef48edcf0635',
             'volume_id': '21ec7341-9256-497b-97d9-ef48edcf0635',
             'provider_auth': None,
             'project_id': 'project',
             'display_name': 'vol1',
             'display_description': 'test volume',
             'volume_type_id': None,
             'provider_location': '11',
             'volume': {"volume_id": '21ec7341-9256-497b-97d9-ef48edcf0635'},
             'volume': {'provider_location': '12'},
             }

test_host = {'host': 'ubuntu001@backend001#OpenStack_Pool',
             'capabilities': {'smartcache': True,
                              'location_info': '210235G7J20000000000',
                              'QoS_support': True,
                              'pool_name': 'OpenStack_Pool',
                              'timestamp': '2015-07-13T11:41:00.513549',
                              'smartpartition': True,
                              'allocated_capacity_gb': 0,
                              'volume_backend_name': 'Huawei18000FCDriver',
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
        'smarttier': '<is> true',
        'smartcache': '<is> true',
        'smartpartition': '<is> true',
        'thin_provisioning_support': '<is> true',
        'thick_provisioning_support': '<is> False',
        'policy': '2',
        'smartcache:cachename': 'cache-test',
        'smartpartition:partitionname': 'partition-test',
    },
    'is_public': True,
    'deleted_at': None,
    'id': u'530a56e1-a1a4-49f3-ab6c-779a6e5d999f',
    'description': None,
}

hypermetro_devices = """
{
    "remote_device": {
        "RestURL": "http://100.115.10.69:8082/deviceManager/rest",
        "UserName":"admin",
        "UserPassword":"Admin@storage2",
        "StoragePool":"StoragePool001",
        "domain_name":"hypermetro_test"}
}
"""

FAKE_FIND_POOL_RESPONSE = {'CAPACITY': '985661440',
                           'ID': '0',
                           'TOTALCAPACITY': '985661440'}

FAKE_CREATE_VOLUME_RESPONSE = {"ID": "1",
                               "NAME": "5mFHcBv4RkCcD+JyrWc0SA"}

FakeConnector = {'initiator': 'iqn.1993-08.debian:01:ec2bff7ac3a3',
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

FAKE_CREATE_VOLUME_RESPONSE = {"ID": "1",
                               "NAME": "5mFHcBv4RkCcD+JyrWc0SA"}

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

# A fake response of success response storage
FAKE_COMMON_SUCCESS_RESPONSE = """
{
    "error": {
        "code": 0
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
        "deviceid": "210235G7J20000000000"
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
        "USERTOTALCAPACITY": "985661440"
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
        "NAME": "5mFHcBv4RkCcD+JyrWc0SA"
    }
}
"""

FAKE_LUN_GET_SUCCESS_RESPONSE = """
{
    "error": {
        "code": 0
    },
    "data": {
        "ID": "11",
        "IOCLASSID": "11",
        "NAME": "5mFHcBv4RkCcD+JyrWc0SA",
        "RUNNINGSTATUS": "2",
        "HEALTHSTATUS": "1",
        "RUNNINGSTATUS": "27",
        "LUNLIST": "",
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
        "CACHEPARTITIONID": ""
    }
}
"""

FAKE_QUERY_ALL_LUN_RESPONSE = """
{
    "error": {
        "code": 0
    },
    "data": [{
        "ID": "1",
        "NAME": "IexzQZJWSXuX2e9I7c8GNQ"
    }]
}
"""

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
FAKE_SNAPSHOT_LIST_INFO_RESPONSE = """
{
    "error": {
        "code": 0
    },
    "data": [{
        "ID": 11,
        "NAME": "wr_LMKAjS7O_VtsEIREGYw"
    },
    {
        "ID": 12,
        "NAME": "SDFAJSDFLKJ"
    },
    {
        "ID": 13,
        "NAME": "s1Ew5v36To-hR2txJitX5Q"
    }]
}
"""

# A fake response of create snapshot response
FAKE_CREATE_SNAPSHOT_INFO_RESPONSE = """
{
    "error": {
        "code": 0
    },
    "data": {
        "ID": 11,
        "NAME": "YheUoRwbSX2BxN7"
    }
}
"""

# A fake response of get snapshot response
FAKE_GET_SNAPSHOT_INFO_RESPONSE = """
{
    "error": {
        "code": 0
    },
    "data": {
        "ID": 11,
        "NAME": "YheUoRwbSX2BxN7"
    }
}
"""

# A fake response of get iscsi response
FAKE_GET_ISCSI_INFO_RESPONSE = """
{
    "data": [{
        "ETHPORTID": "139267",
        "ID": "iqn.oceanstor:21004846fb8ca15f::22003:111.111.101.244",
        "TPGT": "8196",
        "TYPE": 249
    },
    {
        "ETHPORTID": "139268",
        "ID": "iqn.oceanstor:21004846fb8ca15f::22003:111.111.102.244",
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
        "IPV4ADDR": "192.168.1.2",
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
        "IPV4ADDR": "192.168.1.1",
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
        "IPV4ADDR": "192.168.1.1",
        "HEALTHSTATUS": "1",
        "RUNNINGSTATUS": "10"
    },
    {
        "IPV4ADDR": "192.168.1.2",
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
        "TYPE":245
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

FAKE_ISCSI_INITIATOR_RESPONSE = """
{
    "error":{
        "code": 0
    },
    "data":[{
        "CHAPNAME": "mm-user",
        "HEALTHSTATUS": "1",
        "ID": "iqn.1993-08.org.debian:01:9073aba6c6f",
        "ISFREE": "true",
        "MULTIPATHTYPE": "1",
        "NAME": "",
        "OPERATIONSYSTEM": "255",
        "RUNNINGSTATUS": "28",
        "TYPE": 222,
        "USECHAP": "true"
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

FAKE_GET_FC_PORT_RESPONSE = """
{
    "error":{
        "code":0
    },
    "data":[{
        "RUNNINGSTATUS":"10",
        "WWN":"2000643e8c4c5f66",
        "PARENTID":"0A.1"
    }]
}
"""

FAKE_SYSTEM_VERSION_RESPONSE = """
{
    "error":{
        "code": 0
    },
    "data":{
        "PRODUCTVERSION": "V100R001C10"
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

FAKE_HYPERMETRODOMAIN_RESPONSE = """
{
    "error":{
        "code": 0
    },
    "data":{
        "PRODUCTVERSION": "V100R001C10",
        "ID": "11",
        "NAME": "hypermetro_test",
        "RUNNINGSTATUS": "42"
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
        "PARENTID":"0A.1"
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

FAKE_CONNECT_FC_RESPONCE = {
    "driver_volume_type": 'fibre_channel',
    "data": {
        "target_wwn": ["10000090fa0d6754"],
        "target_lun": "1",
        "volume_id": "21ec7341-9256-497b-97d9-ef48edcf0635"
    }
}

FAKE_METRO_INFO_RESPONCE = {
    "error": {
        "code": 0
    },
    "data": {
        "PRODUCTVERSION": "V100R001C10",
        "ID": "11",
        "NAME": "hypermetro_test",
        "RUNNINGSTATUS": "42"
    }
}

# mock login info map
MAP_COMMAND_TO_FAKE_RESPONSE = {}

MAP_COMMAND_TO_FAKE_RESPONSE['/xx/sessions'] = (
    FAKE_GET_LOGIN_STORAGE_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/sessions'] = (
    FAKE_LOGIN_OUT_STORAGE_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/LUN_MIGRATION/POST'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/LUN_MIGRATION?range=[0-100]/GET'] = (
    FAKE_GET_LUN_MIGRATION_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/LUN_MIGRATION/11/DELETE'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

# mock storage info map
MAP_COMMAND_TO_FAKE_RESPONSE['/storagepool'] = (
    FAKE_STORAGE_POOL_RESPONSE)

# mock lun info map
MAP_COMMAND_TO_FAKE_RESPONSE['/lun'] = (
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

MAP_COMMAND_TO_FAKE_RESPONSE['/lun?range=[0-65535]/GET'] = (
    FAKE_QUERY_ALL_LUN_RESPONSE)

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

MAP_COMMAND_TO_FAKE_RESPONSE['/lungroup?range=[0-8191]/GET'] = (
    FAKE_QUERY_LUN_GROUP_INFO_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/lungroup'] = (
    FAKE_QUERY_LUN_GROUP_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/lungroup/associate'] = (
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

MAP_COMMAND_TO_FAKE_RESPONSE['/lun/count?TYPE=11&ASSOCIATEOBJTYPE=256'
                             '&ASSOCIATEOBJID=11/GET'] = (
    FAKE_LUN_COUNT_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/lun/expand/PUT'] = (
    FAKE_LUN_INFO_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/lungroup/associate?ID=12&ASSOCIATEOBJTYPE=11'
                             '&ASSOCIATEOBJID=12/DELETE'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

# mock snapshot info map
MAP_COMMAND_TO_FAKE_RESPONSE['/snapshot'] = (
    FAKE_CREATE_SNAPSHOT_INFO_RESPONSE)

# mock snapshot info map
MAP_COMMAND_TO_FAKE_RESPONSE['/snapshot/11/GET'] = (
    FAKE_GET_SNAPSHOT_INFO_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/snapshot/activate'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/snapshot/stop/PUT'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/snapshot/11/DELETE'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/snapshot?range=[0-32767]/GET'] = (
    FAKE_SNAPSHOT_LIST_INFO_RESPONSE)

# mock QoS info map
MAP_COMMAND_TO_FAKE_RESPONSE['/ioclass/11/GET'] = (
    FAKE_LUN_GET_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/ioclass/11/DELETE'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/ioclass/active/11/PUT'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/ioclass/'] = (
    FAKE_QOS_INFO_RESPONSE)

# mock iscsi info map
MAP_COMMAND_TO_FAKE_RESPONSE['/iscsi_tgt_port/GET'] = (
    FAKE_GET_ISCSI_INFO_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/eth_port/GET'] = (
    FAKE_GET_ETH_INFO_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/eth_port/associate?TYPE=213&ASSOCIATEOBJTYPE'
                             '=257&ASSOCIATEOBJID=11/GET'] = (
    FAKE_GET_ETH_ASSOCIATE_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/iscsidevicename'] = (
    FAKE_GET_ISCSI_DEVICE_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/iscsi_initiator?range=[0-256]/GET'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/iscsi_initiator/'] = (
    FAKE_ISCSI_INITIATOR_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/iscsi_initiator/POST'] = (
    FAKE_ISCSI_INITIATOR_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/iscsi_initiator/PUT'] = (
    FAKE_ISCSI_INITIATOR_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/iscsi_initiator/remove_iscsi_from_host/PUT'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/iscsi_initiator/'
                             'iqn.1993-08.debian:01:ec2bff7ac3a3/PUT'] = (
    FAKE_ISCSI_INITIATOR_RESPONSE)
# mock host info map
MAP_COMMAND_TO_FAKE_RESPONSE['/host?range=[0-65535]/GET'] = (
    FAKE_GET_ALL_HOST_INFO_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/host/1/DELETE'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/host'] = (
    FAKE_CREATE_HOST_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/hostgroup?range=[0-8191]/GET'] = (
    FAKE_GET_ALL_HOST_GROUP_INFO_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/hostgroup'] = (
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


MAP_COMMAND_TO_FAKE_RESPONSE['/hostgroup/associate'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

# mock copy info map
MAP_COMMAND_TO_FAKE_RESPONSE['/luncopy'] = (
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

MAP_COMMAND_TO_FAKE_RESPONSE['/mappingview'] = (
    FAKE_GET_MAPPING_VIEW_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/MAPPINGVIEW/1/GET'] = (
    FAKE_GET_SPEC_MAPPING_VIEW_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/mappingview/1/DELETE'] = (
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
                             'ASSOCIATEOBJTYPE=257&ASSOCIATEOBJID=11/GET'] = (
    FAKE_GET_MAPPING_VIEW_RESPONSE)

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
MAP_COMMAND_TO_FAKE_RESPONSE['/system/'] = (
    FAKE_SYSTEM_VERSION_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/fc_initiator?range=[0-256]/GET'] = (
    FAKE_GET_FC_INI_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/fc_port/GET'] = (
    FAKE_GET_FC_PORT_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/fc_initiator/GET'] = (
    FAKE_GET_FC_PORT_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['fc_initiator?range=[0-100]/GET'] = (
    FAKE_GET_FC_PORT_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/fc_initiator?PARENTTYPE=21&PARENTID=1/GET'] = (
    FAKE_GET_FC_PORT_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/lun/associate/cachepartition/POST'] = (
    FAKE_SYSTEM_VERSION_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/fc_initiator?range=[0-100]&PARENTID=1/GET'] = (
    FAKE_GET_FC_PORT_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/fc_initiator?PARENTTYPE=21&PARENTID=1/GET'] = (
    FAKE_GET_FC_PORT_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/system/'] = (
    FAKE_SYSTEM_VERSION_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/SMARTCACHEPARTITION/0/GET'] = (
    FAKE_SMARTCACHEPARTITION_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/SMARTCACHEPARTITION/REMOVE_ASSOCIATE/PUT'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/cachepartition/0/GET'] = (
    FAKE_SMARTCACHEPARTITION_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/HyperMetroDomain?range=[0-100]/GET'] = (
    FAKE_HYPERMETRODOMAIN_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/HyperMetroPair/POST'] = (
    FAKE_HYPERMETRODOMAIN_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/HyperMetroPair/11/GET'] = (
    FAKE_HYPERMETRODOMAIN_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/HyperMetroPair/disable_hcpair/PUT'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)

MAP_COMMAND_TO_FAKE_RESPONSE['/HyperMetroPair/11/DELETE'] = (
    FAKE_COMMON_SUCCESS_RESPONSE)


def Fake_sleep(time):
    pass


class Fake18000Client(rest_client.RestClient):

    def __init__(self, configuration):
        rest_client.RestClient.__init__(self, configuration)
        self.delete_flag = False
        self.terminateFlag = False
        self.device_id = None
        self.test_fail = False
        self.test_multi_url_flag = False
        self.checkFlag = False
        self.remove_chap_flag = False
        self.cache_not_exist = False
        self.partition_not_exist = False

    def _change_file_mode(self, filepath):
        pass

    def _parse_volume_type(self, volume):
        poolinfo = self._find_pool_info()
        volume_size = self._get_volume_size(poolinfo, volume)

        params = {'LUNType': 0,
                  'WriteType': '1',
                  'PrefetchType': '3',
                  'qos_level': 'Qos-high',
                  'StripUnitSize': '64',
                  'PrefetchValue': '0',
                  'PrefetchTimes': '0',
                  'qos': 'OpenStack_Qos_High',
                  'MirrorSwitch': '1',
                  'tier': 'Tier_high',
                  }

        params['volume_size'] = volume_size
        params['pool_id'] = poolinfo['ID']
        return params

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

    def do_call(self, url=False, data=None, method=None, calltimeout=4):
        url = url.replace('http://100.115.10.69:8082/deviceManager/rest', '')
        command = url.replace('/210235G7J20000000000/', '')
        data = None

        if method:
            command = command + "/" + method

        for item in MAP_COMMAND_TO_FAKE_RESPONSE.keys():
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


class Fake18000ISCSIStorage(huawei_driver.Huawei18000ISCSIDriver):
    """Fake Huawei Storage, Rewrite some methods of HuaweiISCSIDriver."""

    def __init__(self, configuration):
        self.configuration = configuration
        self.xml_file_path = self.configuration.cinder_huawei_conf_file

    def do_setup(self):
        self.restclient = Fake18000Client(configuration=self.configuration)


class Fake18000FCStorage(huawei_driver.Huawei18000FCDriver):
    """Fake Huawei Storage, Rewrite some methods of HuaweiISCSIDriver."""

    def __init__(self, configuration):
        self.configuration = configuration
        self.xml_file_path = self.configuration.cinder_huawei_conf_file
        self.fcsan_lookup_service = None

    def do_setup(self):
        self.restclient = Fake18000Client(configuration=self.configuration)


class Huawei18000ISCSIDriverTestCase(test.TestCase):

    def setUp(self):
        super(Huawei18000ISCSIDriverTestCase, self).setUp()
        self.tmp_dir = tempfile.mkdtemp()
        self.fake_conf_file = self.tmp_dir + '/cinder_huawei_conf.xml'
        self.addCleanup(shutil.rmtree, self.tmp_dir)
        self.create_fake_conf_file()
        self.addCleanup(os.remove, self.fake_conf_file)
        self.configuration = mock.Mock(spec=conf.Configuration)
        self.configuration.cinder_huawei_conf_file = self.fake_conf_file
        self.xml_file_path = self.configuration.cinder_huawei_conf_file
        self.configuration.hypermetro_devices = hypermetro_devices
        self.stubs.Set(time, 'sleep', Fake_sleep)
        driver = Fake18000ISCSIStorage(configuration=self.configuration)
        self.driver = driver
        self.driver.do_setup()
        self.portgroup = 'portgroup-test'
        self.iscsi_iqns = ['iqn.2006-08.com.huawei:oceanstor:21000022a:'
                           ':20503:192.168.1.1',
                           'iqn.2006-08.com.huawei:oceanstor:21000022a:'
                           ':20500:192.168.1.2']
        self.target_ips = ['192.168.1.1',
                           '192.168.1.2']
        self.portgroup_id = 11

    def test_login_success(self):
        device_id = self.driver.restclient.login()
        self.assertEqual('210235G7J20000000000', device_id)

    def test_create_volume_success(self):
        self.driver.restclient.login()

        # Have pool info in the volume.
        test_volume = {'name': 'volume-21ec7341-9256-497b-97d9-ef48edcf0635',
                       'size': 2,
                       'volume_name': 'vol1',
                       'id': '21ec7341-9256-497b-97d9-ef48edcf0635',
                       'volume_id': '21ec7341-9256-497b-97d9-ef48edcf0635',
                       'provider_auth': None,
                       'project_id': 'project',
                       'display_name': 'vol1',
                       'display_description': 'test volume',
                       'volume_type_id': None,
                       'host': 'ubuntu001@backend001#OpenStack_Pool',
                       'provider_location': '11',
                       }
        lun_info = self.driver.create_volume(test_volume)
        self.assertEqual('1', lun_info['provider_location'])

        # No pool info in the volume.
        test_volume = {'name': 'volume-21ec7341-9256-497b-97d9-ef48edcf0635',
                       'size': 2,
                       'volume_name': 'vol1',
                       'id': '21ec7341-9256-497b-97d9-ef48edcf0635',
                       'volume_id': '21ec7341-9256-497b-97d9-ef48edcf0635',
                       'provider_auth': None,
                       'project_id': 'project',
                       'display_name': 'vol1',
                       'display_description': 'test volume',
                       'volume_type_id': None,
                       'host': 'ubuntu001@backend001',
                       'provider_location': '11',
                       }
        lun_info = self.driver.create_volume(test_volume)
        self.assertEqual('1', lun_info['provider_location'])

    def test_delete_volume_success(self):
        self.driver.restclient.login()
        delete_flag = self.driver.delete_volume(test_volume)
        self.assertTrue(delete_flag)

    def test_create_snapshot_success(self):
        self.driver.restclient.login()
        lun_info = self.driver.create_snapshot(test_snap)
        self.assertEqual(11, lun_info['provider_location'])

        test_snap['volume']['provider_location'] = ''
        lun_info = self.driver.create_snapshot(test_snap)
        self.assertEqual(11, lun_info['provider_location'])

        test_snap['volume']['provider_location'] = None
        lun_info = self.driver.create_snapshot(test_snap)
        self.assertEqual(11, lun_info['provider_location'])

    def test_delete_snapshot_success(self):
        self.driver.restclient.login()
        delete_flag = self.driver.delete_snapshot(test_snap)
        self.assertTrue(delete_flag)

    def test_create_volume_from_snapsuccess(self):
        self.driver.restclient.login()
        lun_info = self.driver.create_volume_from_snapshot(test_volume,
                                                           test_volume)
        self.assertEqual('1', lun_info['ID'])

    def test_initialize_connection_success(self):
        self.driver.restclient.login()
        iscsi_properties = self.driver.initialize_connection(test_volume,
                                                             FakeConnector)
        self.assertEqual(1, iscsi_properties['data']['target_lun'])

    def test_terminate_connection_success(self):
        self.driver.restclient.login()
        self.driver.restclient.terminateFlag = True
        self.driver.terminate_connection(test_volume, FakeConnector)
        self.assertTrue(self.driver.restclient.terminateFlag)

    def test_get_volume_status(self):
        self.driver.restclient.login()
        data = self.driver.get_volume_stats()
        self.assertEqual('1.1.1', data['driver_version'])

    def test_extend_volume(self):
        self.driver.restclient.login()
        lun_info = self.driver.extend_volume(test_volume, 3)
        self.assertEqual('1', lun_info['provider_location'])

    def test_login_fail(self):
        self.driver.restclient.test_fail = True
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.restclient.login)

    def test_create_snapshot_fail(self):
        self.driver.restclient.login()
        self.driver.restclient.test_fail = True
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_snapshot, test_snap)

    def test_create_volume_fail(self):
        self.driver.restclient.login()
        self.driver.restclient.test_fail = True
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume, test_volume)

    def test_delete_volume_fail(self):
        self.driver.restclient.login()
        self.driver.restclient.test_fail = True
        delete_flag = self.driver.delete_volume(test_volume)
        self.assertTrue(delete_flag)

    def test_delete_snapshot_fail(self):
        self.driver.restclient.login()
        self.driver.restclient.test_fail = True
        delete_flag = self.driver.delete_volume(test_snap)
        self.assertTrue(delete_flag)

    def test_initialize_connection_fail(self):
        self.driver.restclient.login()
        self.driver.restclient.test_fail = True

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          test_volume, FakeConnector)

    def test_get_default_timeout(self):
        result = huawei_utils.get_default_timeout(self.xml_file_path)
        self.assertEqual('43200', result)

    def test_get_wait_interval(self):
        result = huawei_utils.get_wait_interval(self.xml_file_path,
                                                'LUNReadyWaitInterval')
        self.assertEqual(2, result)

    def test_lun_is_associated_to_lungroup(self):
        self.driver.restclient.login()
        self.driver.restclient.associate_lun_to_lungroup('11', '11')
        result = self.driver.restclient._is_lun_associated_to_lungroup('11',
                                                                       '11')
        self.assertTrue(result)

    def test_lun_is_not_associated_to_lun_group(self):
        self.driver.restclient.login()
        self.driver.restclient.associate_lun_to_lungroup('12', '12')
        self.driver.restclient.remove_lun_from_lungroup('12', '12')
        result = self.driver.restclient._is_lun_associated_to_lungroup('12',
                                                                       '12')
        self.assertFalse(result)

    def test_get_tgtip(self):
        self.driver.restclient.login()
        portg_id = self.driver.restclient.find_tgt_port_group(self.portgroup)
        target_ip = self.driver.restclient._get_tgt_ip_from_portgroup(portg_id)
        self.assertEqual(self.target_ips, target_ip)

    def test_get_iscsi_params(self):
        self.driver.restclient.login()
        (iscsi_iqns, target_ips, portgroup_id) = (
            self.driver.restclient.get_iscsi_params(self.xml_file_path,
                                                    FakeConnector))
        self.assertEqual(self.iscsi_iqns, iscsi_iqns)
        self.assertEqual(self.target_ips, target_ips)
        self.assertEqual(self.portgroup_id, portgroup_id)

    def test_get_lun_conf_params(self):
        self.driver.restclient.login()
        luninfo = huawei_utils.get_lun_conf_params(self.xml_file_path)
        luninfo['pool_id'] = '0'
        luninfo['volume_size'] = 2
        luninfo['volume_description'] = 'test volume'
        luninfo = huawei_utils.init_lun_parameters('5mFHcBv4RkCcD+JyrWc0SA',
                                                   luninfo)
        self.assertEqual('5mFHcBv4RkCcD+JyrWc0SA', luninfo['NAME'])

    def tset_get_iscsi_conf(self):
        self.driver.restclient.login()
        iscsiinfo = huawei_utils.get_iscsi_conf(self.xml_file_path)
        self.assertEqual('iqn.1993-08.debian:01:ec2bff7ac3a3',
                         iscsiinfo['Initiator'])

    def test_check_conf_file(self):
        self.driver.restclient.login()
        self.driver.restclient.checkFlag = True
        huawei_utils.check_conf_file(self.xml_file_path)
        self.assertTrue(self.driver.restclient.checkFlag)

    def test_get_conf_host_os_type(self):
        self.driver.restclient.login()
        host_os = huawei_utils.get_conf_host_os_type('100.97.10.30',
                                                     self.configuration)
        self.assertEqual('0', host_os)

    def test_find_chap_info(self):
        self.driver.restclient.login()
        tmp_dict = {}
        iscsi_info = {}
        tmp_dict['Name'] = 'iqn.1993-08.debian:01:ec2bff7ac3a3'
        tmp_dict['CHAPinfo'] = 'mm-user;mm-user@storage'
        ini_list = [tmp_dict]
        iscsi_info['Initiator'] = ini_list
        initiator_name = FakeConnector['initiator']
        chapinfo = self.driver.restclient.find_chap_info(iscsi_info,
                                                         initiator_name)
        chap_username, chap_password = chapinfo.split(';')
        self.assertEqual('mm-user', chap_username)
        self.assertEqual('mm-user@storage', chap_password)

    def test_find_alua_info(self):
        self.driver.restclient.login()
        tmp_dict = {}
        iscsi_info = {}
        tmp_dict['Name'] = 'iqn.1993-08.debian:01:ec2bff7ac3a3'
        tmp_dict['ALUA'] = '1'
        ini_list = [tmp_dict]
        iscsi_info['Initiator'] = ini_list
        initiator_name = FakeConnector['initiator']
        type = self.driver.restclient._find_alua_info(iscsi_info,
                                                      initiator_name)
        self.assertEqual('1', type)

    def test_find_pool_info(self):
        self.driver.restclient.login()
        pools = {
            "error": {"code": 0},
            "data": [{
                "NAME": "test001",
                "ID": "0",
                "USERFREECAPACITY": "36",
                "USERTOTALCAPACITY": "48",
                "USAGETYPE": constants.BLOCK_STORAGE_POOL_TYPE},
                {"NAME": "test002",
                 "ID": "1",
                 "USERFREECAPACITY": "37",
                 "USERTOTALCAPACITY": "49",
                 "USAGETYPE": constants.FILE_SYSTEM_POOL_TYPE},
                {"NAME": "test003",
                 "ID": "0",
                 "USERFREECAPACITY": "36",
                 "DATASPACE": "35",
                 "USERTOTALCAPACITY": "48",
                 "USAGETYPE": constants.BLOCK_STORAGE_POOL_TYPE}]}
        pool_name = 'test001'
        test_info = {'CAPACITY': '36', 'ID': '0', 'TOTALCAPACITY': '48'}
        pool_info = self.driver.restclient.find_pool_info(pool_name, pools)
        self.assertEqual(test_info, pool_info)

        pool_name = 'test002'
        test_info = {}
        pool_info = self.driver.restclient.find_pool_info(pool_name, pools)
        self.assertEqual(test_info, pool_info)

        pool_name = 'test000'
        test_info = {}
        pool_info = self.driver.restclient.find_pool_info(pool_name, pools)
        self.assertEqual(test_info, pool_info)

        pool_name = 'test003'
        test_info = {'CAPACITY': '35', 'ID': '0', 'TOTALCAPACITY': '48'}
        pool_info = self.driver.restclient.find_pool_info(pool_name, pools)
        self.assertEqual(test_info, pool_info)

    def test_get_smartx_specs_opts(self):
        self.driver.restclient.login()
        smartx_opts = smartx.SmartX().get_smartx_specs_opts(smarttier_opts)
        self.assertEqual('3', smartx_opts['policy'])

    @mock.patch.object(huawei_utils, 'get_volume_qos',
                       return_value={'MAXIOPS': '100',
                                     'IOType': '2'})
    def test_create_smartqos(self, mock_qos_value):
        self.driver.restclient.login()
        lun_info = self.driver.create_volume(test_volume)
        self.assertEqual('1', lun_info['provider_location'])

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
    def test_creat_smartx(self, mock_volume_types, mock_add_lun_to_partition):
        self.driver.restclient.login()
        lun_info = self.driver.create_volume(test_volume)
        self.assertEqual('1', lun_info['provider_location'])

    def test_find_available_qos(self):
        self.driver.restclient.login()
        qos = {'MAXIOPS': '100', 'IOType': '2'}
        fake_qos_info_response_equal = {
            "error": {
                "code": 0
            },
            "data": [{
                "ID": "11",
                "MAXIOPS": "100",
                "IOType": "2",
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
            (qos_id, lun_list) = self.driver.restclient.find_available_qos(qos)
            self.assertEqual((None, []), (qos_id, lun_list))

        # Number of LUNs in QoS is less than 64
        fake_qos_info_response_less = {
            "error": {
                "code": 0
            },
            "data": [{
                "ID": "11",
                "MAXIOPS": "100",
                "IOType": "2",
                "LUNLIST": u'["0", "1", "2"]'
            }]
        }
        with mock.patch.object(rest_client.RestClient, 'get_qos',
                               return_value=fake_qos_info_response_less):
            (qos_id, lun_list) = self.driver.restclient.find_available_qos(qos)
            self.assertEqual(("11", u'["0", "1", "2"]'), (qos_id, lun_list))

    @mock.patch.object(huawei_utils, 'get_volume_params',
                       return_value=fake_hypermetro_opts)
    @mock.patch.object(rest_client.RestClient, 'login_with_ip',
                       return_value='123456789')
    @mock.patch.object(rest_client.RestClient, 'find_all_pools',
                       return_value=FAKE_STORAGE_POOL_RESPONSE)
    @mock.patch.object(rest_client.RestClient, 'find_pool_info',
                       return_value=FAKE_FIND_POOL_RESPONSE)
    @mock.patch.object(rest_client.RestClient, 'create_volume',
                       return_value=FAKE_CREATE_VOLUME_RESPONSE)
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
    def test_create_hypermetro_success(self, mock_logout,
                                       mock_hyper_pair_info,
                                       mock_volume_ready,
                                       mock_hyper_domain,
                                       mock_create_volume,
                                       mock_pool_info,
                                       mock_all_pool_info,
                                       mock_login_return,
                                       mock_hypermetro_opts):
        self.driver.restclient.login()
        metadata = {"hypermetro_id": '11',
                    "remote_lun_id": '1'}
        lun_info = self.driver.create_volume(hyper_volume)
        mock_logout.assert_called_with()
        self.assertEqual(metadata, lun_info['metadata'])

    @mock.patch.object(huawei_utils, 'get_volume_params',
                       return_value=fake_hypermetro_opts)
    @mock.patch.object(rest_client.RestClient, 'login_with_ip',
                       return_value='123456789')
    @mock.patch.object(rest_client.RestClient, 'find_all_pools',
                       return_value=FAKE_STORAGE_POOL_RESPONSE)
    @mock.patch.object(rest_client.RestClient, 'find_pool_info',
                       return_value=FAKE_FIND_POOL_RESPONSE)
    @mock.patch.object(rest_client.RestClient, 'create_volume',
                       return_value=FAKE_CREATE_VOLUME_RESPONSE)
    @mock.patch.object(rest_client.RestClient, 'get_hyper_domain_id',
                       return_value='11')
    @mock.patch.object(hypermetro.HuaweiHyperMetro, '_wait_volume_ready',
                       return_value=True)
    @mock.patch.object(hypermetro.HuaweiHyperMetro,
                       '_create_hypermetro_pair')
    @mock.patch.object(rest_client.RestClient, 'delete_lun',
                       return_value=None)
    @mock.patch.object(rest_client.RestClient, 'logout',
                       return_value=None)
    def test_create_hypermetro_fail(self, mock_logout,
                                    mock_delete_lun,
                                    mock_hyper_pair_info,
                                    mock_volume_ready,
                                    mock_hyper_domain,
                                    mock_create_volume,
                                    mock_pool_info,
                                    mock_all_pool_info,
                                    mock_login_return,
                                    mock_hypermetro_opts):
        self.driver.restclient.login()
        mock_hyper_pair_info.side_effect = exception.VolumeBackendAPIException(
            data='Create hypermetro error.')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume, hyper_volume)
        mock_delete_lun.assert_called_with('1')
        mock_logout.assert_called_with()

    @mock.patch.object(rest_client.RestClient, 'login_with_ip',
                       return_value='123456789')
    @mock.patch.object(rest_client.RestClient, 'check_lun_exist',
                       return_value=True)
    @mock.patch.object(rest_client.RestClient, 'check_hypermetro_exist',
                       return_value=True)
    @mock.patch.object(rest_client.RestClient, 'get_hypermetro_by_id',
                       return_value=FAKE_METRO_INFO_RESPONCE)
    @mock.patch.object(rest_client.RestClient, 'delete_hypermetro',
                       return_value=FAKE_COMMON_SUCCESS_RESPONSE)
    @mock.patch.object(rest_client.RestClient, 'delete_lun',
                       return_value=None)
    @mock.patch.object(rest_client.RestClient, 'logout',
                       return_value=None)
    def test_delete_hypermetro_success(self, mock_logout,
                                       mock_delete_lun,
                                       mock_delete_hypermetro,
                                       mock_metro_info,
                                       mock_check_hyermetro,
                                       mock_lun_exit,
                                       mock_login_info):
        self.driver.restclient.login()
        result = self.driver.delete_volume(hyper_volume)
        mock_logout.assert_called_with()
        self.assertTrue(result)

    @mock.patch.object(rest_client.RestClient, 'login_with_ip',
                       return_value='123456789')
    @mock.patch.object(rest_client.RestClient, 'check_lun_exist',
                       return_value=True)
    @mock.patch.object(rest_client.RestClient, 'check_hypermetro_exist',
                       return_value=True)
    @mock.patch.object(rest_client.RestClient, 'get_hypermetro_by_id',
                       return_value=FAKE_METRO_INFO_RESPONCE)
    @mock.patch.object(rest_client.RestClient, 'delete_hypermetro')
    @mock.patch.object(rest_client.RestClient, 'delete_lun',
                       return_value=None)
    @mock.patch.object(rest_client.RestClient, 'logout',
                       return_value=None)
    def test_delete_hypermetro_fail(self, mock_logout,
                                    mock_delete_lun,
                                    mock_delete_hypermetro,
                                    mock_metro_info,
                                    mock_check_hyermetro,
                                    mock_lun_exit,
                                    mock_login_info):
        self.driver.restclient.login()
        mock_delete_hypermetro.side_effect = (
            exception.VolumeBackendAPIException(data='Delete hypermetro '
                                                'error.'))
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_volume, hyper_volume)
        mock_delete_lun.assert_called_with('11')

    def create_fake_conf_file(self):
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
        controllerip0 = doc.createElement('ControllerIP0')
        controllerip0_text = doc.createTextNode('10.10.10.1')
        controllerip0.appendChild(controllerip0_text)
        storage.appendChild(controllerip0)
        controllerip1 = doc.createElement('ControllerIP1')
        controllerip1_text = doc.createTextNode('10.10.10.2')
        controllerip1.appendChild(controllerip1_text)
        storage.appendChild(controllerip1)
        username = doc.createElement('UserName')
        username_text = doc.createTextNode('admin')
        username.appendChild(username_text)
        storage.appendChild(username)
        userpassword = doc.createElement('UserPassword')
        userpassword_text = doc.createTextNode('Admin@storage')
        userpassword.appendChild(userpassword_text)
        storage.appendChild(userpassword)
        url = doc.createElement('RestURL')
        url_text = doc.createTextNode('http://100.115.10.69:8082/'
                                      'deviceManager/rest/')
        url.appendChild(url_text)
        storage.appendChild(url)

        storagepool = doc.createElement('StoragePool')
        pool_text = doc.createTextNode('OpenStack_Pool')
        storagepool.appendChild(pool_text)
        storage.appendChild(storagepool)

        lun = doc.createElement('LUN')
        config.appendChild(lun)
        storagepool = doc.createElement('StoragePool')
        pool_text = doc.createTextNode('OpenStack_Pool;OpenStack_Pool2')
        storagepool.appendChild(pool_text)
        lun.appendChild(storagepool)

        timeout = doc.createElement('Timeout')
        timeout_text = doc.createTextNode('43200')
        timeout.appendChild(timeout_text)
        lun.appendChild(timeout)

        lun_ready_wait_interval = doc.createElement('LUNReadyWaitInterval')
        lun_ready_wait_interval_text = doc.createTextNode('2')
        lun_ready_wait_interval.appendChild(lun_ready_wait_interval_text)
        lun.appendChild(lun_ready_wait_interval)

        prefetch = doc.createElement('Prefetch')
        prefetch.setAttribute('Type', '1')
        prefetch.setAttribute('Value', '0')
        lun.appendChild(prefetch)

        iscsi = doc.createElement('iSCSI')
        config.appendChild(iscsi)
        defaulttargetip = doc.createElement('DefaultTargetIP')
        defaulttargetip_text = doc.createTextNode('100.115.10.68')
        defaulttargetip.appendChild(defaulttargetip_text)
        iscsi.appendChild(defaulttargetip)
        initiator = doc.createElement('Initiator')
        initiator.setAttribute('Name', 'iqn.1993-08.debian:01:ec2bff7ac3a3')
        initiator.setAttribute('TargetIP', '192.168.1.2')
        initiator.setAttribute('CHAPinfo', 'mm-user;mm-user@storage')
        initiator.setAttribute('ALUA', '1')
        initiator.setAttribute('TargetPortGroup', 'portgroup-test')
        iscsi.appendChild(initiator)

        host = doc.createElement('Host')
        host.setAttribute('HostIP', '100.97.10.30')
        host.setAttribute('OSType', 'Linux')
        config.appendChild(host)

        fakefile = open(self.fake_conf_file, 'w')
        fakefile.write(doc.toprettyxml(indent=''))
        fakefile.close()


class FCSanLookupService(object):
    def get_device_mapping_from_network(self, initiator_list,
                                        target_list):
        return fake_fabric_mapping


class Huawei18000FCDriverTestCase(test.TestCase):

    def setUp(self):
        super(Huawei18000FCDriverTestCase, self).setUp()
        self.tmp_dir = tempfile.mkdtemp()
        self.fake_conf_file = self.tmp_dir + '/cinder_huawei_conf.xml'
        self.addCleanup(shutil.rmtree, self.tmp_dir)
        self.create_fake_conf_file()
        self.addCleanup(os.remove, self.fake_conf_file)
        self.configuration = mock.Mock(spec=conf.Configuration)
        self.configuration.cinder_huawei_conf_file = self.fake_conf_file
        self.xml_file_path = self.configuration.cinder_huawei_conf_file
        self.configuration.hypermetro_devices = hypermetro_devices
        self.stubs.Set(time, 'sleep', Fake_sleep)
        driver = Fake18000FCStorage(configuration=self.configuration)
        self.driver = driver
        self.driver.do_setup()

    def test_login_success(self):
        device_id = self.driver.restclient.login()
        self.assertEqual('210235G7J20000000000', device_id)

    def test_create_volume_success(self):
        self.driver.restclient.login()
        lun_info = self.driver.create_volume(test_volume)
        self.assertEqual('1', lun_info['provider_location'])

    def test_delete_volume_success(self):
        self.driver.restclient.login()
        delete_flag = self.driver.delete_volume(test_volume)
        self.assertTrue(delete_flag)

    def test_create_snapshot_success(self):
        self.driver.restclient.login()
        lun_info = self.driver.create_snapshot(test_snap)
        self.assertEqual(11, lun_info['provider_location'])

        test_snap['volume']['provider_location'] = ''
        lun_info = self.driver.create_snapshot(test_snap)
        self.assertEqual(11, lun_info['provider_location'])

        test_snap['volume']['provider_location'] = None
        lun_info = self.driver.create_snapshot(test_snap)
        self.assertEqual(11, lun_info['provider_location'])

    def test_delete_snapshot_success(self):
        self.driver.restclient.login()
        delete_flag = self.driver.delete_snapshot(test_snap)
        self.assertTrue(delete_flag)

    def test_create_volume_from_snapsuccess(self):
        self.driver.restclient.login()
        lun_info = self.driver.create_volume_from_snapshot(test_volume,
                                                           test_volume)
        self.assertEqual('1', lun_info['ID'])

    def test_initialize_connection_success(self):
        self.driver.restclient.login()
        iscsi_properties = self.driver.initialize_connection(test_volume,
                                                             FakeConnector)
        self.assertEqual(1, iscsi_properties['data']['target_lun'])

    def test_terminate_connection_success(self):
        self.driver.restclient.login()
        self.driver.restclient.terminateFlag = True
        self.driver.terminate_connection(test_volume, FakeConnector)
        self.assertTrue(self.driver.restclient.terminateFlag)

    def test_get_volume_status(self):
        self.driver.restclient.login()
        data = self.driver.get_volume_stats()
        self.assertEqual('1.1.1', data['driver_version'])

    def test_extend_volume(self):
        self.driver.restclient.login()
        lun_info = self.driver.extend_volume(test_volume, 3)
        self.assertEqual('1', lun_info['provider_location'])

    def test_login_fail(self):
        self.driver.restclient.test_fail = True
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.restclient.login)

    def test_create_snapshot_fail(self):
        self.driver.restclient.login()
        self.driver.restclient.test_fail = True
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_snapshot, test_snap)

    def test_create_volume_fail(self):
        self.driver.restclient.login()
        self.driver.restclient.test_fail = True
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume, test_volume)

    def test_delete_volume_fail(self):
        self.driver.restclient.login()
        self.driver.restclient.test_fail = True
        delete_flag = self.driver.delete_volume(test_volume)
        self.assertTrue(delete_flag)

    def test_delete_snapshot_fail(self):
        self.driver.restclient.login()
        self.driver.restclient.test_fail = True
        delete_flag = self.driver.delete_snapshot(test_snap)
        self.assertTrue(delete_flag)

    def test_initialize_connection_fail(self):
        self.driver.restclient.login()
        self.driver.restclient.test_fail = True
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          test_volume, FakeConnector)

    def test_get_default_timeout(self):
        result = huawei_utils.get_default_timeout(self.xml_file_path)
        self.assertEqual('43200', result)

    def test_get_wait_interval(self):
        result = huawei_utils.get_wait_interval(self.xml_file_path,
                                                'LUNReadyWaitInterval')
        self.assertEqual(2, result)

    def test_lun_is_associated_to_lungroup(self):
        self.driver.restclient.login()
        self.driver.restclient.associate_lun_to_lungroup('11', '11')
        result = self.driver.restclient._is_lun_associated_to_lungroup('11',
                                                                       '11')
        self.assertTrue(result)

    def test_lun_is_not_associated_to_lun_group(self):
        self.driver.restclient.login()
        self.driver.restclient.associate_lun_to_lungroup('12', '12')
        self.driver.restclient.remove_lun_from_lungroup('12', '12')
        result = self.driver.restclient._is_lun_associated_to_lungroup('12',
                                                                       '12')
        self.assertFalse(result)

    def test_get_lun_conf_params(self):
        self.driver.restclient.login()
        luninfo = huawei_utils.get_lun_conf_params(self.xml_file_path)
        luninfo['pool_id'] = '0'
        luninfo['volume_size'] = 2
        luninfo['volume_description'] = 'test volume'
        luninfo = huawei_utils.init_lun_parameters('5mFHcBv4RkCcD+JyrWc0SA',
                                                   luninfo)
        self.assertEqual('5mFHcBv4RkCcD+JyrWc0SA', luninfo['NAME'])

    def test_check_conf_file(self):
        self.driver.restclient.login()
        self.driver.restclient.checkFlag = True
        huawei_utils.check_conf_file(self.xml_file_path)
        self.assertTrue(self.driver.restclient.checkFlag)

    def test_get_conf_host_os_type(self):
        self.driver.restclient.login()
        host_os = huawei_utils.get_conf_host_os_type('100.97.10.30',
                                                     self.configuration)
        self.assertEqual('0', host_os)

    @mock.patch.object(rest_client.RestClient, 'add_lun_to_partition')
    def test_migrate_volume_success(self, mock_add_lun_to_partition):
        self.driver.restclient.login()

        # Migrate volume without new type.
        model_update = None
        moved = False
        empty_dict = {}
        # Migrate volume without new type.
        moved, model_update = self.driver.migrate_volume(None,
                                                         test_volume,
                                                         test_host,
                                                         None)
        self.assertTrue(moved)
        self.assertEqual(empty_dict, model_update)

        # Migrate volume with new type.
        moved = False
        empty_dict = {}
        new_type = {'extra_specs':
                    {'smarttier': '<is> true',
                     'smartcache': '<is> true',
                     'smartpartition': '<is> true',
                     'thin_provisioning_support': '<is> true',
                     'thick_provisioning_support': '<is> False',
                     'policy': '2',
                     'smartcache:cachename': 'cache-test',
                     'smartpartition:partitionname': 'partition-test'}}
        moved, model_update = self.driver.migrate_volume(None,
                                                         test_volume,
                                                         test_host,
                                                         new_type)
        self.assertTrue(moved)
        self.assertEqual(empty_dict, model_update)

    def test_migrate_volume_fail(self):
        self.driver.restclient.login()
        self.driver.restclient.test_fail = True

        # Migrate volume without new type.
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.migrate_volume, None,
                          test_volume, test_host, None)

        # Migrate volume with new type.
        new_type = {'extra_specs':
                    {'smarttier': '<is> true',
                     'smartcache': '<is> true',
                     'thin_provisioning_support': '<is> true',
                     'thick_provisioning_support': '<is> False',
                     'policy': '2',
                     'smartcache:cachename': 'cache-test',
                     'partitionname': 'partition-test'}}
        self.driver.restclient.test_fail = True
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.migrate_volume, None,
                          test_volume, test_host, new_type)

    def test_check_migration_valid(self):
        self.driver.restclient.login()
        is_valid = self.driver._check_migration_valid(test_host,
                                                      test_volume)
        self.assertTrue(is_valid)
        # No pool_name in capabilities.
        invalid_host1 = {'host': 'ubuntu001@backend002#OpenStack_Pool',
                         'capabilities':
                             {'location_info': '210235G7J20000000000',
                              'allocated_capacity_gb': 0,
                              'volume_backend_name': 'Huawei18000FCDriver',
                              'storage_protocol': 'FC'}}
        is_valid = self.driver._check_migration_valid(invalid_host1,
                                                      test_volume)
        self.assertFalse(is_valid)
        # location_info in capabilities is not matched.
        invalid_host2 = {'host': 'ubuntu001@backend002#OpenStack_Pool',
                         'capabilities':
                             {'location_info': '210235G7J20000000001',
                              'allocated_capacity_gb': 0,
                              'pool_name': 'OpenStack_Pool',
                              'volume_backend_name': 'Huawei18000FCDriver',
                              'storage_protocol': 'FC'}}
        is_valid = self.driver._check_migration_valid(invalid_host2,
                                                      test_volume)
        self.assertFalse(is_valid)
        # storage_protocol is not match current protocol and volume status is
        # 'in-use'.
        volume_in_use = {'name': 'volume-21ec7341-9256-497b-97d9-ef48edcf0635',
                         'size': 2,
                         'volume_name': 'vol1',
                         'id': '21ec7341-9256-497b-97d9-ef48edcf0635',
                         'volume_id': '21ec7341-9256-497b-97d9-ef48edcf0635',
                         'volume_attachment': 'in-use',
                         'provider_location': '11'}
        invalid_host2 = {'host': 'ubuntu001@backend002#OpenStack_Pool',
                         'capabilities':
                             {'location_info': '210235G7J20000000001',
                              'allocated_capacity_gb': 0,
                              'pool_name': 'OpenStack_Pool',
                              'volume_backend_name': 'Huawei18000FCDriver',
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
                              'volume_backend_name': 'Huawei18000FCDriver',
                              'storage_protocol': 'iSCSI'}}
        is_valid = self.driver._check_migration_valid(invalid_host3,
                                                      test_volume)
        self.assertFalse(is_valid)

    @mock.patch.object(rest_client.RestClient, 'rename_lun')
    def test_update_migrated_volume_success(self, mock_rename_lun):
        self.driver.restclient.login()
        original_volume = {'id': '21ec7341-9256-497b-97d9-ef48edcf0635'}
        current_volume = {'id': '21ec7341-9256-497b-97d9-ef48edcf0636'}
        model_update = self.driver.update_migrated_volume(None,
                                                          original_volume,
                                                          current_volume,
                                                          'available')
        self.assertEqual({'_name_id': None}, model_update)

    @mock.patch.object(rest_client.RestClient, 'rename_lun')
    def test_update_migrated_volume_fail(self, mock_rename_lun):
        self.driver.restclient.login()
        mock_rename_lun.side_effect = exception.VolumeBackendAPIException(
            data='Error occurred.')
        original_volume = {'id': '21ec7341-9256-497b-97d9-ef48edcf0635'}
        current_volume = {'id': '21ec7341-9256-497b-97d9-ef48edcf0636',
                          '_name_id': '21ec7341-9256-497b-97d9-ef48edcf0637'}
        model_update = self.driver.update_migrated_volume(None,
                                                          original_volume,
                                                          current_volume,
                                                          'available')
        self.assertEqual({'_name_id': '21ec7341-9256-497b-97d9-ef48edcf0637'},
                         model_update)

    @mock.patch.object(rest_client.RestClient, 'add_lun_to_partition')
    def test_retype_volume_success(self, mock_add_lun_to_partition):
        self.driver.restclient.login()
        retype = self.driver.retype(None, test_volume,
                                    test_new_type, None, test_host)
        self.assertTrue(retype)

    def test_retype_volume_cache_fail(self):
        self.driver.restclient.cache_not_exist = True
        self.driver.restclient.login()
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.retype, None,
                          test_volume, test_new_type, None, test_host)

    def test_retype_volume_partition_fail(self):
        self.driver.restclient.partition_not_exist = True
        self.driver.restclient.login()
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.retype, None,
                          test_volume, test_new_type, None, test_host)

    @mock.patch.object(rest_client.RestClient, 'add_lun_to_partition')
    def test_retype_volume_fail(self, mock_add_lun_to_partition):
        self.driver.restclient.login()
        mock_add_lun_to_partition.side_effect = (
            exception.VolumeBackendAPIException(data='Error occurred.'))
        retype = self.driver.retype(None, test_volume,
                                    test_new_type, None, test_host)
        self.assertFalse(retype)

    def test_build_ini_targ_map(self):
        self.driver.restclient.login()
        fake_lookup_service = FCSanLookupService()
        fake_lookup_service.get_device_mapping_from_network = mock.Mock(
            return_value=fake_fabric_mapping)

        zone_helper = fc_zone_helper.FCZoneHelper(
            fake_lookup_service, self.driver.restclient)
        (tgt_port_wwns,
         init_targ_map) = (zone_helper.build_ini_targ_map(
             ['10000090fa0d6754']))
        target_port_wwns = ['2000643e8c4c5f66']
        ini_target_map = {'10000090fa0d6754': ['2000643e8c4c5f66']}
        self.assertEqual(target_port_wwns, tgt_port_wwns)
        self.assertEqual(ini_target_map, init_targ_map)

    def test_filter_port_by_contr(self):
        self.driver.restclient.login()
        # Six ports in one fabric.
        ports_in_fabric = ['1', '2', '3', '4', '5', '6']
        # Ports 1,3,4,7 belonged to controller A
        # Ports 2,5,8 belonged to controller B
        # ports 6 belonged to controller C
        total_port_contr_map = {'1': 'A', '3': 'A', '4': 'A', '7': 'A',
                                '2': 'B', '5': 'B', '8': 'B',
                                '6': 'C'}
        zone_helper = fc_zone_helper.FCZoneHelper(None, None)
        filtered_ports = zone_helper._filter_port_by_contr(
            ports_in_fabric, total_port_contr_map)
        expected_filtered_ports = ['1', '3', '2', '5', '6']
        self.assertEqual(expected_filtered_ports, filtered_ports)

    def test_multi_resturls_success(self):
        self.driver.restclient.login()
        self.driver.restclient.test_multi_url_flag = True
        lun_info = self.driver.create_volume(test_volume)
        self.assertEqual('1', lun_info['provider_location'])

    def test_get_id_from_result(self):
        self.driver.restclient.login()
        result = {}
        name = 'test_name'
        key = 'NAME'
        re = self.driver.restclient._get_id_from_result(result, name, key)
        self.assertIsNone(re)

        result = {'data': {}}
        re = self.driver.restclient._get_id_from_result(result, name, key)
        self.assertIsNone(re)

        result = {'data': [{'COUNT': 1, 'ID': '1'},
                           {'COUNT': 2, 'ID': '2'}]}

        re = self.driver.restclient._get_id_from_result(result, name, key)
        self.assertIsNone(re)

        result = {'data': [{'NAME': 'test_name1', 'ID': '1'},
                           {'NAME': 'test_name2', 'ID': '2'}]}
        re = self.driver.restclient._get_id_from_result(result, name, key)
        self.assertIsNone(re)

        result = {'data': [{'NAME': 'test_name', 'ID': '1'},
                           {'NAME': 'test_name2', 'ID': '2'}]}
        re = self.driver.restclient._get_id_from_result(result, name, key)
        self.assertEqual('1', re)

    @mock.patch.object(rest_client.RestClient, 'find_pool_info',
                       return_value={'ID': 1,
                                     'CAPACITY': 110362624,
                                     'TOTALCAPACITY': 209715200})
    def test_get_capacity(self, mock_find_pool_info):
        expected_pool_capacity = {'total_capacity': 100.0,
                                  'free_capacity': 52.625}
        pool_capacity = self.driver.restclient._get_capacity(None,
                                                             None)
        self.assertEqual(expected_pool_capacity, pool_capacity)

    @mock.patch.object(huawei_utils, 'get_volume_params',
                       return_value=fake_hypermetro_opts)
    @mock.patch.object(rest_client.RestClient, 'login_with_ip',
                       return_value='123456789')
    @mock.patch.object(rest_client.RestClient, 'find_all_pools',
                       return_value=FAKE_STORAGE_POOL_RESPONSE)
    @mock.patch.object(rest_client.RestClient, 'find_pool_info',
                       return_value=FAKE_FIND_POOL_RESPONSE)
    @mock.patch.object(rest_client.RestClient, 'create_volume',
                       return_value=FAKE_CREATE_VOLUME_RESPONSE)
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
                                       mock_create_volume,
                                       mock_hyper_domain,
                                       mock_volume_ready,
                                       mock_pair_info,
                                       mock_logout):
        self.driver.restclient.login()
        metadata = {"hypermetro_id": '11',
                    "remote_lun_id": '1'}
        lun_info = self.driver.create_volume(hyper_volume)
        self.assertEqual(metadata, lun_info['metadata'])

    def create_fake_conf_file(self):
        """Create a fake Config file

        Huawei storage customize a XML configuration file,
        the configuration file is used to set the Huawei storage custom
        parameters, therefore, in the UT test we need to simulate such a
        configuration file
        """
        doc = minidom.Document()

        config = doc.createElement('config')
        doc.appendChild(config)

        storage = doc.createElement('Storage')
        config.appendChild(storage)
        controllerip0 = doc.createElement('ControllerIP0')
        controllerip0_text = doc.createTextNode('10.10.10.1')
        controllerip0.appendChild(controllerip0_text)
        storage.appendChild(controllerip0)
        controllerip1 = doc.createElement('ControllerIP1')
        controllerip1_text = doc.createTextNode('10.10.10.2')
        controllerip1.appendChild(controllerip1_text)
        storage.appendChild(controllerip1)
        username = doc.createElement('UserName')
        username_text = doc.createTextNode('admin')
        username.appendChild(username_text)
        storage.appendChild(username)
        userpassword = doc.createElement('UserPassword')
        userpassword_text = doc.createTextNode('Admin@storage')
        userpassword.appendChild(userpassword_text)
        storage.appendChild(userpassword)

        protocol = doc.createElement('Protocol')
        protocol_text = doc.createTextNode('FC')
        protocol.appendChild(protocol_text)
        storage.appendChild(protocol)

        url = doc.createElement('RestURL')
        url_text = doc.createTextNode('http://100.115.10.69:8082/'
                                      'deviceManager/rest/')
        url.appendChild(url_text)
        storage.appendChild(url)

        storagepool = doc.createElement('StoragePool')
        pool_text = doc.createTextNode('OpenStack_Pool')
        storagepool.appendChild(pool_text)
        storage.appendChild(storagepool)

        lun = doc.createElement('LUN')
        config.appendChild(lun)
        storagepool = doc.createElement('StoragePool')
        pool_text = doc.createTextNode('OpenStack_Pool;OpenStack_Pool2')
        storagepool.appendChild(pool_text)
        lun.appendChild(storagepool)

        lun_type = doc.createElement('LUNType')
        lun_type_text = doc.createTextNode('Thick')
        lun_type.appendChild(lun_type_text)
        lun.appendChild(lun_type)

        timeout = doc.createElement('Timeout')
        timeout_text = doc.createTextNode('43200')
        timeout.appendChild(timeout_text)
        lun.appendChild(timeout)

        lun_ready_wait_interval = doc.createElement('LUNReadyWaitInterval')
        lun_ready_wait_interval_text = doc.createTextNode('2')
        lun_ready_wait_interval.appendChild(lun_ready_wait_interval_text)
        lun.appendChild(lun_ready_wait_interval)

        iscsi = doc.createElement('iSCSI')
        config.appendChild(iscsi)
        defaulttargetip = doc.createElement('DefaultTargetIP')
        defaulttargetip_text = doc.createTextNode('100.115.10.68')
        defaulttargetip.appendChild(defaulttargetip_text)
        iscsi.appendChild(defaulttargetip)
        initiator = doc.createElement('Initiator')
        initiator.setAttribute('Name', 'iqn.1993-08.debian:01:ec2bff7ac3a3')
        initiator.setAttribute('TargetIP', '192.168.1.2')
        iscsi.appendChild(initiator)

        prefetch = doc.createElement('Prefetch')
        prefetch.setAttribute('Type', '1')
        prefetch.setAttribute('Value', '0')
        lun.appendChild(prefetch)

        host = doc.createElement('Host')
        host.setAttribute('HostIP', '100.97.10.30')
        host.setAttribute('OSType', 'Linux')
        config.appendChild(host)

        fakefile = open(self.fake_conf_file, 'w')
        fakefile.write(doc.toprettyxml(indent=''))
        fakefile.close()
