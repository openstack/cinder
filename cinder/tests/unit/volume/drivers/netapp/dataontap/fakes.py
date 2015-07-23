# Copyright (c) - 2014, Clinton Knight.  All rights reserved.
# Copyright (c) - 2015, Tom Barron.  All rights reserved.
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

from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api

VOLUME_ID = 'f10d1a84-9b7b-427e-8fec-63c48b509a56'
LUN_ID = 'ee6b4cc7-477b-4016-aa0c-7127b4e3af86'
LUN_HANDLE = 'fake_lun_handle'
LUN_NAME = 'lun1'
LUN_SIZE = 3
LUN_TABLE = {LUN_NAME: None}
SIZE = 1024
HOST_NAME = 'fake.host.name'
BACKEND_NAME = 'fake_backend_name'
POOL_NAME = 'aggr1'
SHARE_IP = '192.168.99.24'
EXPORT_PATH = '/fake/export/path'
NFS_SHARE = '%s:%s' % (SHARE_IP, EXPORT_PATH)
HOST_STRING = '%s@%s#%s' % (HOST_NAME, BACKEND_NAME, POOL_NAME)
NFS_HOST_STRING = '%s@%s#%s' % (HOST_NAME, BACKEND_NAME, NFS_SHARE)
FLEXVOL = 'openstack-flexvol'
NFS_FILE_PATH = 'nfsvol'
PATH = '/vol/%s/%s' % (POOL_NAME, LUN_NAME)
LUN_METADATA = {
    'OsType': None,
    'SpaceReserved': 'true',
    'Path': PATH,
    'Qtree': None,
    'Volume': POOL_NAME,
}
VOLUME = {
    'name': LUN_NAME,
    'size': SIZE,
    'id': VOLUME_ID,
    'host': HOST_STRING,
}
NFS_VOLUME = {
    'name': NFS_FILE_PATH,
    'size': SIZE,
    'id': VOLUME_ID,
    'host': NFS_HOST_STRING,
}

NETAPP_VOLUME = 'fake_netapp_volume'

UUID1 = '12345678-1234-5678-1234-567812345678'
LUN_PATH = '/vol/vol0/%s' % LUN_NAME

VSERVER_NAME = 'openstack-vserver'

FC_VOLUME = {'name': 'fake_volume'}

FC_INITIATORS = ['21000024ff406cc3', '21000024ff406cc2']
FC_FORMATTED_INITIATORS = ['21:00:00:24:ff:40:6c:c3',
                           '21:00:00:24:ff:40:6c:c2']

FC_TARGET_WWPNS = ['500a098280feeba5', '500a098290feeba5',
                   '500a098190feeba5', '500a098180feeba5']

FC_FORMATTED_TARGET_WWPNS = ['50:0a:09:82:80:fe:eb:a5',
                             '50:0a:09:82:90:fe:eb:a5',
                             '50:0a:09:81:90:fe:eb:a5',
                             '50:0a:09:81:80:fe:eb:a5']

FC_CONNECTOR = {'ip': '1.1.1.1',
                'host': 'fake_host',
                'wwnns': ['20000024ff406cc3', '20000024ff406cc2'],
                'wwpns': ['21000024ff406cc3', '21000024ff406cc2']}

FC_I_T_MAP = {'21000024ff406cc3': ['500a098280feeba5', '500a098290feeba5'],
              '21000024ff406cc2': ['500a098190feeba5', '500a098180feeba5']}

FC_I_T_MAP_COMPLETE = {'21000024ff406cc3': FC_TARGET_WWPNS,
                       '21000024ff406cc2': FC_TARGET_WWPNS}

FC_FABRIC_MAP = {'fabricB':
                 {'target_port_wwn_list':
                  ['500a098190feeba5', '500a098180feeba5'],
                  'initiator_port_wwn_list': ['21000024ff406cc2']},
                 'fabricA':
                 {'target_port_wwn_list':
                  ['500a098290feeba5', '500a098280feeba5'],
                  'initiator_port_wwn_list': ['21000024ff406cc3']}}

FC_TARGET_INFO = {'driver_volume_type': 'fibre_channel',
                  'data': {'target_lun': 1,
                           'initiator_target_map': FC_I_T_MAP,
                           'access_mode': 'rw',
                           'target_wwn': FC_TARGET_WWPNS,
                           'target_discovered': True}}

FC_TARGET_INFO_EMPTY = {'driver_volume_type': 'fibre_channel', 'data': {}}

FC_TARGET_INFO_UNMAP = {'driver_volume_type': 'fibre_channel',
                        'data': {'target_wwn': FC_TARGET_WWPNS,
                                 'initiator_target_map': FC_I_T_MAP}}

IGROUP1_NAME = 'openstack-igroup1'

IGROUP1 = {
    'initiator-group-os-type': 'linux',
    'initiator-group-type': 'fcp',
    'initiator-group-name': IGROUP1_NAME,
}

ISCSI_VOLUME = {
    'name': 'fake_volume',
    'id': 'fake_id',
    'provider_auth': 'fake provider auth',
}

ISCSI_LUN = {'name': ISCSI_VOLUME, 'lun_id': 42}

ISCSI_SERVICE_IQN = 'fake_iscsi_service_iqn'

ISCSI_CONNECTION_PROPERTIES = {
    'data': {
        'auth_method': 'fake',
        'auth_password': 'auth',
        'auth_username': 'provider',
        'target_discovered': False,
        'target_iqn': ISCSI_SERVICE_IQN,
        'target_lun': 42,
        'target_portal': '1.2.3.4:3260',
        'volume_id': 'fake_id',
    },
    'driver_volume_type': 'iscsi',
}

ISCSI_CONNECTOR = {
    'ip': '1.1.1.1',
    'host': 'fake_host',
    'initiator': 'fake_initiator_iqn',
}

ISCSI_TARGET_DETAILS_LIST = [
    {'address': '5.6.7.8', 'port': '3260'},
    {'address': '1.2.3.4', 'port': '3260'},
    {'address': '99.98.97.96', 'port': '3260'},
]

IPV4_ADDRESS = '192.168.14.2'
IPV6_ADDRESS = 'fe80::6e40:8ff:fe8a:130'
NFS_SHARE_IPV4 = IPV4_ADDRESS + ':' + EXPORT_PATH
NFS_SHARE_IPV6 = IPV6_ADDRESS + ':' + EXPORT_PATH

RESERVED_PERCENTAGE = 7
TOTAL_BYTES = 4797892092432
AVAILABLE_BYTES = 13479932478
CAPACITY_VALUES = (TOTAL_BYTES, AVAILABLE_BYTES)

IGROUP1 = {'initiator-group-os-type': 'linux',
           'initiator-group-type': 'fcp',
           'initiator-group-name': IGROUP1_NAME}

QOS_SPECS = {}
EXTRA_SPECS = {}
MAX_THROUGHPUT = '21734278B/s'
QOS_POLICY_GROUP_NAME = 'fake_qos_policy_group_name'

QOS_POLICY_GROUP_INFO_LEGACY = {
    'legacy': 'legacy-' + QOS_POLICY_GROUP_NAME,
    'spec': None,
}

QOS_POLICY_GROUP_SPEC = {
    'max_throughput': MAX_THROUGHPUT,
    'policy_name': QOS_POLICY_GROUP_NAME,
}

QOS_POLICY_GROUP_INFO = {'legacy': None, 'spec': QOS_POLICY_GROUP_SPEC}

CLONE_SOURCE_NAME = 'fake_clone_source_name'
CLONE_SOURCE_ID = 'fake_clone_source_id'
CLONE_SOURCE_SIZE = 1024

CLONE_SOURCE = {
    'size': CLONE_SOURCE_SIZE,
    'name': CLONE_SOURCE_NAME,
    'id': CLONE_SOURCE_ID,
}

CLONE_DESTINATION_NAME = 'fake_clone_destination_name'
CLONE_DESTINATION_SIZE = 1041
CLONE_DESTINATION_ID = 'fake_clone_destination_id'

CLONE_DESTINATION = {
    'size': CLONE_DESTINATION_SIZE,
    'name': CLONE_DESTINATION_NAME,
    'id': CLONE_DESTINATION_ID,
}

SNAPSHOT = {
    'name': 'fake_snapshot_name',
    'volume_size': SIZE,
    'volume_id': 'fake_volume_id',
}

VOLUME_REF = {'name': 'fake_vref_name', 'size': 42}

FILE_LIST = ['file1', 'file2', 'file3']

FAKE_LUN = netapp_api.NaElement.create_node_with_children(
    'lun-info',
    **{'alignment': 'indeterminate',
       'block-size': '512',
       'comment': '',
       'creation-timestamp': '1354536362',
       'is-space-alloc-enabled': 'false',
       'is-space-reservation-enabled': 'true',
       'mapped': 'false',
       'multiprotocol-type': 'linux',
       'online': 'true',
       'path': '/vol/fakeLUN/fakeLUN',
       'prefix-size': '0',
       'qtree': '',
       'read-only': 'false',
       'serial-number': '2FfGI$APyN68',
       'share-state': 'none',
       'size': '20971520',
       'size-used': '0',
       'staging': 'false',
       'suffix-size': '0',
       'uuid': 'cec1f3d7-3d41-11e2-9cf4-123478563412',
       'volume': 'fakeLUN',
       'vserver': 'fake_vserver'})
