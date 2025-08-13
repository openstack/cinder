# Copyright (c) - 2014, Clinton Knight.  All rights reserved.
# Copyright (c) - 2015, Tom Barron.  All rights reserved.
# Copyright (c) - 2016 Chuck Fouts. All rights reserved.
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

from lxml import etree

from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api


VOLUME_ID = 'f10d1a84-9b7b-427e-8fec-63c48b509a56'
LUN_ID = 'ee6b4cc7-477b-4016-aa0c-7127b4e3af86'
LUN_HANDLE = 'fake_lun_handle'
NAMESPACE_HANDLE = 'fake_namespace_handle'
LUN_NAME = 'lun1'
NAMESPACE_NAME = 'namespace1'
LUN_SIZE = 3
LUN_TABLE = {LUN_NAME: None}
SIZE = 1024
HOST_NAME = 'fake.host.name'
BACKEND_NAME = 'fake_backend_name'
POOL_NAME = 'aggr1'
SHARE_IP = '192.168.99.24'
IPV6_ADDRESS = 'fe80::6e40:8ff:fe8a:130'
EXPORT_PATH = '/fake/export/path'
NFS_SHARE = '%s:%s' % (SHARE_IP, EXPORT_PATH)
NFS_SHARE_IPV6 = '[%s]:%s' % (IPV6_ADDRESS, EXPORT_PATH)
HOST_STRING = '%s@%s#%s' % (HOST_NAME, BACKEND_NAME, POOL_NAME)
NFS_HOST_STRING = '%s@%s#%s' % (HOST_NAME, BACKEND_NAME, NFS_SHARE)
AGGREGATE = 'aggr1'
FLEXVOL = 'openstack-flexvol'
NFS_FILE_PATH = 'nfsvol'
PATH = '/vol/%s/%s' % (POOL_NAME, LUN_NAME)
PATH_NAMESPACE = '/vol/%s/%s' % (POOL_NAME, NAMESPACE_NAME)
IMAGE_FILE_ID = 'img-cache-imgid'
PROVIDER_LOCATION = 'fake_provider_location'
NFS_HOST = 'nfs-host1'
NFS_SHARE_PATH = '/export'
NFS_EXPORT_1 = '%s:%s' % (NFS_HOST, NFS_SHARE_PATH)
NFS_EXPORT_2 = 'nfs-host2:/export'
MOUNT_POINT = '/mnt/nfs'
ATTACHED = 'attached'
DETACHED = 'detached'
DEST_POOL_NAME = 'dest-aggr'
DEST_VSERVER_NAME = 'dest-vserver'
DEST_BACKEND_NAME = 'dest-backend'
DEST_HOST_STRING = '%s@%s#%s' % (HOST_NAME, DEST_BACKEND_NAME, DEST_POOL_NAME)
DEST_EXPORT_PATH = '/fake/export/dest-path'
DEST_NFS_SHARE = '%s:%s' % (SHARE_IP, DEST_EXPORT_PATH)
CLUSTER_NAME = 'fake-cluster-name'
DEST_CLUSTER_NAME = 'fake-dest-cluster-name'
JOB_UUID = 'fb132b04-6422-43ce-9451-ee819f0131a4'
LUN_METADATA = {
    'OsType': None,
    'SpaceReserved': 'true',
    'SpaceAllocated': 'false',
    'Path': PATH,
    'Qtree': None,
    'Volume': POOL_NAME,
}
LUN_METADATA_WITH_SPACE_ALLOCATION = {
    'OsType': None,
    'SpaceReserved': 'true',
    'Path': PATH,
    'SpaceAllocated': 'true',
    'Qtree': None,
    'Volume': POOL_NAME,
}
NAMESPACE_METADATA = {
    'OsType': None,
    'Path': PATH_NAMESPACE,
    'Qtree': None,
    'Volume': POOL_NAME,
}
VOLUME = {
    'name': LUN_NAME,
    'size': SIZE,
    'id': VOLUME_ID,
    'host': HOST_STRING,
    'attach_status': DETACHED,
}
NAMESPACE_VOLUME = {
    'name': NAMESPACE_NAME,
    'size': SIZE,
    'id': VOLUME_ID,
    'host': HOST_STRING,
    'attach_status': DETACHED,
}
NFS_VOLUME = {
    'name': NFS_FILE_PATH,
    'size': SIZE,
    'id': VOLUME_ID,
    'host': NFS_HOST_STRING,
    'provider_location': PROVIDER_LOCATION,
}

FAKE_MANAGE_VOLUME = {
    'name': 'volume-new-managed-123',
    'id': 'volume-new-managed-123',
}

FAKE_IMAGE_LOCATION = (
    None,
    [
        # valid metadata
        {
            'metadata': {
                'share_location': 'nfs://host/path',
                'mountpoint': '/opt/stack/data/glance',
                'id': 'abc-123',
                'type': 'nfs'
            },
            'url': 'file:///opt/stack/data/glance/image-id-0'
        },
        # missing metadata
        {
            'metadata': {},
            'url': 'file:///opt/stack/data/glance/image-id-1'
        },
        # missing location_type
        {
            'metadata': {'location_type': None},
            'url': 'file:///opt/stack/data/glance/image-id-2'
        },
        # non-nfs location_type
        {
            'metadata': {'location_type': 'not-NFS'},
            'url': 'file:///opt/stack/data/glance/image-id-3'
        },
        # missing share_location
        {
            'metadata': {'location_type': 'nfs', 'share_location': None},
            'url': 'file:///opt/stack/data/glance/image-id-4'},
        # missing mountpoint
        {
            'metadata': {
                'location_type': 'nfs',
                'share_location': 'nfs://host/path',
                # Pre-kilo we documented "mount_point"
                'mount_point': '/opt/stack/data/glance'
            },
            'url': 'file:///opt/stack/data/glance/image-id-5'
        },
        # Valid metadata
        {
            'metadata':
                {
                    'share_location': 'nfs://host/path',
                    'mountpoint': '/opt/stack/data/glance',
                    'id': 'abc-123',
                    'type': 'nfs',
                },
            'url': 'file:///opt/stack/data/glance/image-id-6'
        }
    ]
)

NETAPP_VOLUME = 'fake_netapp_volume'

VFILER = 'fake_netapp_vfiler'

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
                           'target_wwn': FC_TARGET_WWPNS,
                           'target_discovered': True}}

FC_TARGET_INFO_EMPTY = {'driver_volume_type': 'fibre_channel', 'data': {}}

FC_TARGET_INFO_UNMAP = {'driver_volume_type': 'fibre_channel',
                        'data': {'target_wwn': FC_TARGET_WWPNS,
                                 'initiator_target_map': FC_I_T_MAP}}

ISCSI_ONE_MAP_LIST = [{'initiator-group': 'openstack-faketgt1',
                       'vserver': 'vserver_123', 'lun-id': '1'}]
ISCSI_MULTI_MAP_LIST = [{'initiator-group': 'openstack-faketgt1',
                        'vserver': 'vserver_123', 'lun-id': '1'},
                        {'initiator-group': 'openstack-faketgt2',
                         'vserver': 'vserver_123', 'lun-id': '2'}
                        ]
ISCSI_EMPTY_MAP_LIST = []

IGROUP1_NAME = 'openstack-igroup1'

IGROUP1 = {
    'initiator-group-os-type': 'linux',
    'initiator-group-type': 'fcp',
    'initiator-group-name': IGROUP1_NAME,
}

CUSTOM_IGROUP = {
    'initiator-group-os-type': 'linux',
    'initiator-group-type': 'fcp',
    'initiator-group-name': 'node1',
}

ISCSI_VOLUME = {
    'name': 'fake_volume',
    'id': 'fake_id',
    'provider_auth': 'fake provider auth',
    'provider_location': 'iscsi:/dummy_path'
}

ISCSI_LUN = {'name': ISCSI_VOLUME, 'lun_id': 42}

ISCSI_SERVICE_IQN = 'fake_iscsi_service_iqn'

ISCSI_CONNECTION_PROPERTIES = {
    'data': {
        'auth_method': 'fake_method',
        'auth_password': 'auth',
        'auth_username': 'provider',
        'discard': True,
        'discovery_auth_method': 'fake_method',
        'discovery_auth_username': 'provider',
        'discovery_auth_password': 'auth',
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
NFS_SHARE_IPV4 = IPV4_ADDRESS + ':' + EXPORT_PATH

RESERVED_PERCENTAGE = 7
MAX_OVER_SUBSCRIPTION_RATIO = 19.0
TOTAL_BYTES = 4797892092432
AVAILABLE_BYTES = 13479932478
CAPACITY_VALUES = (TOTAL_BYTES, AVAILABLE_BYTES)
CAPACITIES = {'size-total': TOTAL_BYTES, 'size-available': AVAILABLE_BYTES}

IGROUP1 = {'initiator-group-os-type': 'linux',
           'initiator-group-type': 'fcp',
           'initiator-group-name': IGROUP1_NAME}

QOS_SPECS = {}
EXTRA_SPECS = {'netapp:space_allocation': '<is> True'}
MAX_THROUGHPUT = '21734278B/s'
MIN_IOPS = '256iops'
MAX_IOPS = '512iops'
MAX_BPS = '1000000B/s'
QOS_POLICY_GROUP_NAME = 'fake_qos_policy_group_name'

QOS_POLICY_GROUP_INFO_LEGACY = {
    'legacy': 'legacy-' + QOS_POLICY_GROUP_NAME,
    'spec': None,
}

QOS_POLICY_GROUP_SPEC = {
    'min_throughput': MIN_IOPS,
    'max_throughput': MAX_IOPS,
    'policy_name': QOS_POLICY_GROUP_NAME,
}

QOS_POLICY_GROUP_SPEC_BPS = {
    'max_throughput': MAX_BPS,
    'policy_name': QOS_POLICY_GROUP_NAME,
}

QOS_POLICY_GROUP_SPEC_MAX = {
    'max_throughput': MAX_THROUGHPUT,
    'policy_name': QOS_POLICY_GROUP_NAME,
}

EXPECTED_IOPS_PER_GB = '128'
PEAK_IOPS_PER_GB = '512'
EXPECTED_IOPS_ALLOCATION = 'used-space'
PEAK_IOPS_ALLOCATION = 'used-space'
ABSOLUTE_MIN_IOPS = '75'
BLOCK_SIZE = 'ANY'
ADAPTIVE_QOS_SPEC = {
    'policy_name': QOS_POLICY_GROUP_NAME,
    'expected_iops': EXPECTED_IOPS_PER_GB,
    'peak_iops': PEAK_IOPS_PER_GB,
    'expected_iops_allocation': EXPECTED_IOPS_ALLOCATION,
    'peak_iops_allocation': PEAK_IOPS_ALLOCATION,
    'absolute_min_iops': ABSOLUTE_MIN_IOPS,
    'block_size': BLOCK_SIZE,
}

QOS_POLICY_GROUP_INFO = {'legacy': None, 'spec': QOS_POLICY_GROUP_SPEC}
QOS_POLICY_GROUP_INFO_MAX = {'legacy': None, 'spec': QOS_POLICY_GROUP_SPEC_MAX}
ADAPTIVE_QOS_POLICY_GROUP_INFO = {
    'legacy': None,
    'spec': ADAPTIVE_QOS_SPEC,
}

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

VOLUME_NAME = 'volume-fake_volume_id'
VOLUME_PATH = '/vol/%s/%s' % (NETAPP_VOLUME, VOLUME_NAME)
MOUNT_PATH = '168.10.16.11:/' + VOLUME_ID
SNAPSHOT_NAME = 'fake_snapshot_name'
SNAPSHOT_LUN_HANDLE = 'fake_snapshot_lun_handle'
SNAPSHOT_NAMESPACE_HANDLE = 'fake_snapshot_namespace_handle'

SNAPSHOT_MOUNT = '/fake/mount/path'

SNAPSHOT = {
    'name': SNAPSHOT_NAME,
    'volume_size': SIZE,
    'volume_id': VOLUME_ID,
    'volume_name': VOLUME_NAME,
    'volume_type_id': 'fake_id',
    'busy': False,
    'id': 'fake_id'
}

SNAPSHOT_VOLUME = {
    'id': VOLUME_ID,
    'name': VOLUME_NAME
}

LUN_WITH_METADATA = {
    'handle': 'vserver_fake:/vol/fake_flexvol/volume-fake-uuid',
    'name': 'volume-fake-uuid',
    'size': 20971520,
    'metadata': {
        'Vserver': 'vserver_fake',
        'Volume': 'fake_flexvol',
        'Qtree': None,
        'Path': '/vol/fake_flexvol/volume-fake-uuid',
        'OsType': 'linux',
        'SpaceReserved': 'false',
        'UUID': 'fake-uuid'
    }
}

NAMESPACE_WITH_METADATA = {
    'handle': 'vserver_fake:/vol/fake_flexvol/volume-fake-uuid',
    'name': 'volume-fake-uuid',
    'size': 20971520,
    'metadata': {
        'Vserver': 'vserver_fake',
        'Volume': 'fake_flexvol',
        'Qtree': None,
        'Path': '/vol/fake_flexvol/volume-fake-uuid',
        'OsType': 'linux',
        'SpaceReserved': 'false',
        'UUID': 'fake-uuid'
    }
}

VOLUME_REF = {'name': 'fake_vref_name', 'size': 42}

FAKE_CMODE_VOLUMES = ['open123', 'mixed', 'open321']
FAKE_CMODE_POOL_MAP = {
    'open123': {
        'pool_name': 'open123',
    },
    'mixed': {
        'pool_name': 'mixed',
    },
    'open321': {
        'pool_name': 'open321',
    },
}

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

FAKE_LUN_GET_ITER_RESULT = [
    {
        'Vserver': 'fake_vserver',
        'Volume': 'fake_volume',
        'Size': 123,
        'Qtree': 'fake_qtree',
        'Path': 'fake_path',
        'OsType': 'fake_os',
        'SpaceReserved': 'true',
        'UUID': 'fake-uuid',
    },
]

CG_VOLUME_NAME = 'fake_cg_volume'
CG_GROUP_NAME = 'fake_consistency_group'
CG_POOL_NAME = 'cdot'
SOURCE_CG_VOLUME_NAME = 'fake_source_cg_volume'
CG_VOLUME_ID = 'fake_cg_volume_id'
CG_VOLUME_SIZE = 100
SOURCE_CG_VOLUME_ID = 'fake_source_cg_volume_id'
CONSISTENCY_GROUP_NAME = 'fake_cg'
SOURCE_CONSISTENCY_GROUP_ID = 'fake_source_cg_id'
CONSISTENCY_GROUP_ID = 'fake_cg_id'
CG_SNAPSHOT_ID = 'fake_cg_snapshot_id'
CG_SNAPSHOT_NAME = 'snapshot-' + CG_SNAPSHOT_ID
CG_VOLUME_SNAPSHOT_ID = 'fake_cg_volume_snapshot_id'

CG_LUN_METADATA = {
    'OsType': None,
    'Path': '/vol/aggr1/fake_cg_volume',
    'SpaceReserved': 'true',
    'Qtree': None,
    'Volume': POOL_NAME,
}

SOURCE_CG_VOLUME = {
    'name': SOURCE_CG_VOLUME_NAME,
    'size': CG_VOLUME_SIZE,
    'id': SOURCE_CG_VOLUME_ID,
    'host': 'hostname@backend#cdot',
    'consistencygroup_id': None,
    'status': 'fake_status',
}

CG_VOLUME = {
    'name': CG_VOLUME_NAME,
    'size': 100,
    'id': CG_VOLUME_ID,
    'host': 'hostname@backend#' + CG_POOL_NAME,
    'consistencygroup_id': CONSISTENCY_GROUP_ID,
    'status': 'fake_status',
}

SOURCE_CONSISTENCY_GROUP = {
    'id': SOURCE_CONSISTENCY_GROUP_ID,
    'status': 'fake_status',
}

CONSISTENCY_GROUP = {
    'id': CONSISTENCY_GROUP_ID,
    'status': 'fake_status',
    'name': CG_GROUP_NAME,
}

CG_CONTEXT = {}

CG_SNAPSHOT = {
    'id': CG_SNAPSHOT_ID,
    'name': CG_SNAPSHOT_NAME,
    'volume_size': CG_VOLUME_SIZE,
    'consistencygroup_id': CONSISTENCY_GROUP_ID,
    'status': 'fake_status',
    'volume_id': 'fake_source_volume_id',
}

CG_VOLUME_SNAPSHOT = {
    'name': CG_SNAPSHOT_NAME,
    'volume_size': CG_VOLUME_SIZE,
    'cgsnapshot_id': CG_SNAPSHOT_ID,
    'id': CG_VOLUME_SNAPSHOT_ID,
    'status': 'fake_status',
    'volume_id': CG_VOLUME_ID,
}

AFF_SYSTEM_NODE_GET_ITER_RESPONSE = etree.XML("""
  <results status="passed">
    <attributes-list>
      <node-details-info>
        <node-model>AFFA400</node-model>
        <node>aff-node1</node>
        <is-all-flash-optimized>true</is-all-flash-optimized>
        <is-all-flash-select-optimized>false</is-all-flash-select-optimized>
      </node-details-info>
      <node-details-info>
        <node-model>AFFA400</node-model>
        <node>aff-node2</node>
        <is-all-flash-optimized>true</is-all-flash-optimized>
        <is-all-flash-select-optimized>false</is-all-flash-select-optimized>
      </node-details-info>
    </attributes-list>
    <num-records>2</num-records>
  </results>
""")

FAS_SYSTEM_NODE_GET_ITER_RESPONSE = etree.XML("""
  <results status="passed">
    <attributes-list>
      <node-details-info>
        <node-model>FAS2554</node-model>
        <node>fas-node1</node>
        <is-all-flash-optimized>false</is-all-flash-optimized>
        <is-all-flash-select-optimized>false</is-all-flash-select-optimized>
      </node-details-info>
      <node-details-info>
        <node-model>FAS2554</node-model>
        <node>fas-node2</node>
        <is-all-flash-optimized>false</is-all-flash-optimized>
        <is-all-flash-select-optimized>false</is-all-flash-select-optimized>
      </node-details-info>
    </attributes-list>
    <num-records>2</num-records>
  </results>
""")

HYBRID_SYSTEM_NODE_GET_ITER_RESPONSE = etree.XML("""
  <results status="passed">
    <attributes-list>
      <node-details-info>
        <node>select-node</node>
        <is-all-flash-optimized>false</is-all-flash-optimized>
        <is-all-flash-select-optimized>true</is-all-flash-select-optimized>
        <node-model>FDvM300</node-model>
      </node-details-info>
      <node-details-info>
        <node>c190-node</node>
        <is-all-flash-optimized>true</is-all-flash-optimized>
        <is-all-flash-select-optimized>false</is-all-flash-select-optimized>
        <node-model>AFF-C190</node-model>
      </node-details-info>
    </attributes-list>
    <num-records>2</num-records>
  </results>
""")

AFF_NODE = {
    'model': 'AFFA400',
    'is_all_flash': True,
    'is_all_flash_select': False,
}
AFF_NODE_1 = AFF_NODE.copy()
AFF_NODE_1['name'] = 'aff-node1'
AFF_NODE_2 = AFF_NODE.copy()
AFF_NODE_2['name'] = 'aff-node2'

FAS_NODE = {
    'model': 'FAS2554',
    'is_all_flash': False,
    'is_all_flash_select': False,
}
FAS_NODE_1 = FAS_NODE.copy()
FAS_NODE_1['name'] = 'fas-node1'
FAS_NODE_2 = FAS_NODE.copy()
FAS_NODE_2['name'] = 'fas-node2'

SELECT_NODE = {
    'model': 'FDvM300',
    'is_all_flash': False,
    'is_all_flash_select': True,
    'name': 'select-node',
}
C190_NODE = {
    'model': 'AFF-C190',
    'is_all_flash': True,
    'is_all_flash_select': False,
    'name': 'c190-node',
}

AFF_SYSTEM_NODES_INFO = [AFF_NODE_1, AFF_NODE_2]
FAS_SYSTEM_NODES_INFO = [FAS_NODE_1, FAS_NODE_2]
HYBRID_SYSTEM_NODES_INFO = [SELECT_NODE, C190_NODE]

SYSTEM_GET_VERSION_RESPONSE = etree.XML("""
  <results status="passed">
    <build-timestamp>1395426307</build-timestamp>
    <is-clustered>true</is-clustered>
    <version>NetApp Release 9.6P2: Fri Jul 19 06:06:59 UTC 2019</version>
    <version-tuple>
      <system-version-tuple>
        <generation>9</generation>
        <major>6</major>
        <minor>0</minor>
      </system-version-tuple>
    </version-tuple>
  </results>
""")


VG_VOLUME_NAME = 'fake_vg_volume'
VG_GROUP_NAME = 'fake_volume_group'
VG_POOL_NAME = 'cdot'
SOURCE_VG_VOLUME_NAME = 'fake_source_vg_volume'
VG_VOLUME_ID = 'fake_vg_volume_id'
VG_VOLUME_SIZE = 100
SOURCE_VG_VOLUME_ID = 'fake_source_vg_volume_id'
VOLUME_GROUP_NAME = 'fake_vg'
SOURCE_VOLUME_GROUP_ID = 'fake_source_vg_id'
VOLUME_GROUP_ID = 'fake_vg_id'
VG_SNAPSHOT_ID = 'fake_vg_snapshot_id'
VG_SNAPSHOT_NAME = 'snapshot-' + VG_SNAPSHOT_ID
VG_VOLUME_SNAPSHOT_ID = 'fake_vg_volume_snapshot_id'
MIN_SIZE_FOR_A_LUN = '4194304'
MAX_SIZE_FOR_A_LUN = '17555678822400'

VG_LUN_METADATA = {
    'OsType': None,
    'Path': '/vol/aggr1/fake_vg_volume',
    'SpaceReserved': 'true',
    'Qtree': None,
    'Volume': POOL_NAME,
}

SOURCE_VG_VOLUME = {
    'name': SOURCE_VG_VOLUME_NAME,
    'size': VG_VOLUME_SIZE,
    'id': SOURCE_VG_VOLUME_ID,
    'host': 'hostname@backend#cdot',
    'volumegroup_id': None,
    'status': 'fake_status',
    'provider_location': PROVIDER_LOCATION,
}

VG_VOLUME = {
    'name': VG_VOLUME_NAME,
    'size': 100,
    'id': VG_VOLUME_ID,
    'host': 'hostname@backend#' + VG_POOL_NAME,
    'volumegroup_id': VOLUME_GROUP_ID,
    'status': 'fake_status',
    'provider_location': PROVIDER_LOCATION,
}

SOURCE_VOLUME_GROUP = {
    'id': SOURCE_VOLUME_GROUP_ID,
    'status': 'fake_status',
}

VOLUME_GROUP = {
    'id': VOLUME_GROUP_ID,
    'status': 'fake_status',
    'name': VG_GROUP_NAME,
    'host': 'fake_host',
}

VG_CONTEXT = {}

VG_SNAPSHOT = {
    'id': VG_SNAPSHOT_ID,
    'name': VG_SNAPSHOT_NAME,
    'volume_size': VG_VOLUME_SIZE,
    'volumegroup_id': VOLUME_GROUP_ID,
    'status': 'fake_status',
    'volume_id': 'fake_source_volume_id',
    'volume': VG_VOLUME,
}

VG_VOLUME_SNAPSHOT = {
    'name': VG_SNAPSHOT_NAME,
    'volume_size': VG_VOLUME_SIZE,
    'vgsnapshot_id': VG_SNAPSHOT_ID,
    'id': VG_VOLUME_SNAPSHOT_ID,
    'status': 'fake_status',
    'volume_id': VG_VOLUME_ID,
}


class test_volume(object):

    def __getitem__(self, key):
        return getattr(self, key)


test_volume = test_volume()
test_volume.id = {'vserver': 'openstack', 'name': 'vola'}
test_volume.aggr = {
    'disk_type': 'SSD',
    'ha_policy': 'cfo',
    'junction': '/vola',
    'name': 'aggr1',
    'raid_type': 'raiddp',
}
test_volume.export = {'path': NFS_SHARE}
test_volume.sis = {'dedup': False, 'compression': False}
test_volume.state = {
    'status': 'online',
    'vserver_root': False,
    'junction_active': True,
}
test_volume.qos = {'qos_policy_group': None}
test_volume.host = 'fakehost@backbackend#fakepool'
test_volume.name = 'fakename'
test_volume.size = SIZE
test_volume.multiattach = False


class test_namespace_volume(object):

    def __getitem__(self, key):
        return getattr(self, key)


test_namespace_volume = test_namespace_volume()
test_namespace_volume.name = NAMESPACE_NAME
test_namespace_volume.size = SIZE
test_namespace_volume.id = VOLUME_ID
test_namespace_volume.host = HOST_STRING
test_namespace_volume.attach_status = DETACHED


class test_snapshot(object):
    pass

    def __getitem__(self, key):
        return getattr(self, key)


test_snapshot = test_snapshot()
test_snapshot.id = 'fake_snap_id'
test_snapshot.name = 'snapshot-%s' % test_snapshot.id
test_snapshot.volume_id = 'fake_volume_id'
test_snapshot.provider_location = PROVIDER_LOCATION


class test_iscsi_attachment(object):
    def __getattr__(self, key):
        return getattr(self, key)


test_iscsi_attachment = test_iscsi_attachment()
test_iscsi_attachment.connector = ISCSI_CONNECTOR


def get_fake_net_interface_get_iter_response():
    return etree.XML("""<results status="passed">
        <num-records>1</num-records>
        <attributes-list>
            <net-interface-info></net-interface-info>
            <address>FAKE_IP</address>
        </attributes-list>
    </results>""")


def get_fake_ifs():
    return [{'vserver': VSERVER_NAME}]


AFF_SYSTEM_NODE_GET_ITER_RESPONSE_REST = {
    "records": [
        {
            "uuid": "9eff6c76-fc13-11ea-8799-525400",
            "name": "aff-node1",
            "model": "AFFA400",
            "is_all_flash_optimized": True,
            "is_all_flash_select_optimized": False,
            "_links": {
                "self": {
                    "href": "/api/cluster/nodes/9eff6c76-fc13-11ea-8799-525400"
                }
            }
        },
        {
            "uuid": "9eff6c76-fc13-11ea-8799-52540006bba9",
            "name": "aff-node2",
            "model": "AFFA400",
            "is_all_flash_optimized": True,
            "is_all_flash_select_optimized": False,
            "_links": {
                "self": {
                    "href": "/api/cluster/nodes/9eff6c76-fc13-11ea-8799-525400"
                }
            }
        }
    ],
    "num_records": 2,
    "_links": {
        "self": {
            "href": "/api/cluster/nodes?fields=model,name,"
                    "is_all_flash_optimized,is_all_flash_select_optimized"
        }
    }
}

FAS_SYSTEM_NODE_GET_ITER_RESPONSE_REST = {
    "records": [
        {
            "uuid": "9eff6c76-fc13-11ea-8799-52540006bba9",
            "name": "fas-node1",
            "model": "FAS2554",
            "is_all_flash_optimized": False,
            "is_all_flash_select_optimized": False,
            "_links": {
                "self": {
                    "href": "/api/cluster/nodes/9eff6c76-fc13-11ea-8799-525400"
                }
            }
        },
        {
            "uuid": "9eff6c76-fc13-11ea-8799-52540006bba9",
            "name": "fas-node2",
            "model": "FAS2554",
            "is_all_flash_optimized": False,
            "is_all_flash_select_optimized": False,
            "_links": {
                "self": {
                    "href": "/api/cluster/nodes/9eff6c76-fc13-11ea-8799-525400"
                }
            }
        }
    ],
    "num_records": 2,
    "_links": {
        "self": {
            "href": "/api/cluster/nodes?fields=model,name,"
                    "is_all_flash_optimized,is_all_flash_select_optimized"
        }
    }
}

HYBRID_SYSTEM_NODE_GET_ITER_RESPONSE_REST = {
    "records": [
        {
            "uuid": "9eff6c76-fc13-11ea-8799-52540006bba9",
            "name": "select-node",
            "model": "FDvM300",
            "is_all_flash_optimized": False,
            "is_all_flash_select_optimized": True,
            "_links": {
                "self": {
                    "href": "/api/cluster/nodes/9eff6c76-fc13-11ea-8799-525400"
                }
            }
        },
        {
            "uuid": "9eff6c76-fc13-11ea-8799-52540006bba9",
            "name": "c190-node",
            "model": "AFF-C190",
            "is_all_flash_optimized": True,
            "is_all_flash_select_optimized": False,
            "_links": {
                "self": {
                    "href": "/api/cluster/nodes/9eff6c76-fc13-11ea-8799-525400"
                }
            }
        }
    ],
    "num_records": 2,
    "_links": {
        "self": {
            "href": "/api/cluster/nodes?fields=model,name,"
                    "is_all_flash_optimized,is_all_flash_select_optimized"
        }
    }
}

QOS_POLICY_BY_NAME_RESPONSE_REST = {
    "records": [
        {
            "uuid": "9eff6c76-fc13-11ea-8799-52540006bba9",
            "name": "openstack-cd-uuid",
            "_links": {
                "self": {
                    "href": "/api/storage/qos/policies/"
                            "9eff6c76-fc13-11ea-8799-52540006bba9"
                }
            }
        }
    ],
    "num_records": 1,
    "_links": {
        "self": {
            "href": "/api/storage/qos/policies?fields=name"
        }
    }
}

QOS_SPECS_REST = {}
MAX_THROUGHPUT_REST = '21734278'
MIN_IOPS_REST = '256'
MAX_IOPS_REST = '512'
MAX_BPS_REST = '1'

QOS_POLICY_GROUP_INFO_LEGACY_REST = {
    'legacy': 'legacy-' + QOS_POLICY_GROUP_NAME,
    'spec': None,
}

QOS_POLICY_GROUP_SPEC_REST = {
    'min_throughput': MIN_IOPS_REST,
    'max_throughput': MAX_IOPS_REST,
    'policy_name': QOS_POLICY_GROUP_NAME,
}

QOS_POLICY_GROUP_API_ARGS_REST = {
    'name': QOS_POLICY_GROUP_NAME,
    'svm': {
        'name': VSERVER_NAME
    },
    'fixed': {
        'max_throughput_iops': int(MAX_IOPS_REST),
        'min_throughput_iops': int(MIN_IOPS_REST)
    }
}

QOS_POLICY_GROUP_API_ARGS_REST_BPS = {
    'name': QOS_POLICY_GROUP_NAME,
    'svm': {
        'name': VSERVER_NAME
    },
    'fixed': {
        'max_throughput_mbps': int(MAX_BPS_REST),
    }
}

QOS_POLICY_GROUP_SPEC_MAX_REST = {
    'max_throughput': MAX_THROUGHPUT_REST,
    'policy_name': QOS_POLICY_GROUP_NAME,
}

EXPECTED_IOPS_PER_GB_REST = '128'
PEAK_IOPS_PER_GB_REST = '512'
PEAK_IOPS_ALLOCATION_REST = 'used-space'
EXPECTED_IOPS_ALLOCATION_REST = 'used-space'
ABSOLUTE_MIN_IOPS_REST = '75'
BLOCK_SIZE_REST = 'ANY'
ADAPTIVE_QOS_SPEC_REST = {
    'policy_name': QOS_POLICY_GROUP_NAME,
    'expected_iops': EXPECTED_IOPS_PER_GB_REST,
    'expected_iops_allocation': EXPECTED_IOPS_ALLOCATION_REST,
    'peak_iops': PEAK_IOPS_PER_GB_REST,
    'peak_iops_allocation': PEAK_IOPS_ALLOCATION_REST,
    'absolute_min_iops': ABSOLUTE_MIN_IOPS_REST,
    'block_size': BLOCK_SIZE_REST,
}

ADAPTIVE_QOS_API_ARGS_REST = {
    'name': QOS_POLICY_GROUP_NAME,
    'svm': {
        'name': VSERVER_NAME
    },
    'adaptive': {
        'absolute_min_iops': int(ABSOLUTE_MIN_IOPS_REST),
        'expected_iops': int(EXPECTED_IOPS_PER_GB_REST),
        'expected_iops_allocation': EXPECTED_IOPS_ALLOCATION_REST,
        'peak_iops': int(PEAK_IOPS_PER_GB_REST),
        'peak_iops_allocation': PEAK_IOPS_ALLOCATION_REST,
        'block_size': BLOCK_SIZE_REST,
    }
}

QOS_POLICY_GROUP_INFO_REST = {
    'legacy': None, 'spec': QOS_POLICY_GROUP_SPEC_REST}
QOS_POLICY_GROUP_INFO_MAX_REST = {
    'legacy': None, 'spec': QOS_POLICY_GROUP_SPEC_MAX_REST}
ADAPTIVE_QOS_POLICY_GROUP_INFO_REST = {
    'legacy': None,
    'spec': ADAPTIVE_QOS_SPEC_REST,
}

REST_FIELDS = 'uuid,name,style'
SUBSYSTEM = 'openstack-fake-subsystem'
HOST_NQN = 'nqn.1992-01.example.com:string'
TARGET_NQN = 'nqn.1992-01.example.com:target'
