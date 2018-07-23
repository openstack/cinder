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
AGGREGATE = 'aggr1'
FLEXVOL = 'openstack-flexvol'
NFS_FILE_PATH = 'nfsvol'
PATH = '/vol/%s/%s' % (POOL_NAME, LUN_NAME)
IMAGE_FILE_ID = 'img-cache-imgid'
PROVIDER_LOCATION = 'fake_provider_location'
NFS_HOST = 'nfs-host1'
NFS_SHARE_PATH = '/export'
NFS_EXPORT_1 = '%s:%s' % (NFS_HOST, NFS_SHARE_PATH)
NFS_EXPORT_2 = 'nfs-host2:/export'
MOUNT_POINT = '/mnt/nfs'
ATTACHED = 'attached'
DETACHED = 'detached'
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

ISCSI_VOLUME = {
    'name': 'fake_volume',
    'id': 'fake_id',
    'provider_auth': 'fake provider auth',
}

ISCSI_LUN = {'name': ISCSI_VOLUME, 'lun_id': 42}

ISCSI_SERVICE_IQN = 'fake_iscsi_service_iqn'

ISCSI_CONNECTION_PROPERTIES = {
    'data': {
        'auth_method': 'fake_method',
        'auth_password': 'auth',
        'auth_username': 'provider',
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
IPV6_ADDRESS = 'fe80::6e40:8ff:fe8a:130'
NFS_SHARE_IPV4 = IPV4_ADDRESS + ':' + EXPORT_PATH
NFS_SHARE_IPV6 = IPV6_ADDRESS + ':' + EXPORT_PATH

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

VOLUME_NAME = 'volume-fake_volume_id'
MOUNT_PATH = '168.10.16.11:/' + VOLUME_ID
SNAPSHOT_NAME = 'fake_snapshot_name'
SNAPSHOT_LUN_HANDLE = 'fake_snapshot_lun_handle'
SNAPSHOT_MOUNT = '/fake/mount/path'

SNAPSHOT = {
    'name': SNAPSHOT_NAME,
    'volume_size': SIZE,
    'volume_id': VOLUME_ID,
    'volume_name': VOLUME_NAME,
    'busy': False,
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

FAKE_7MODE_VOLUME = {
    'all': [
        netapp_api.NaElement(
            etree.XML("""<volume-info xmlns="http://www.netapp.com/filer/admin">
            <name>open123</name>
            </volume-info>""")),
        netapp_api.NaElement(
            etree.XML("""<volume-info xmlns="http://www.netapp.com/filer/admin">
            <name>mixed3</name>
            </volume-info>""")),
        netapp_api.NaElement(
            etree.XML("""<volume-info xmlns="http://www.netapp.com/filer/admin">
            <name>open1234</name>
            </volume-info>"""))
    ],
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

FAKE_7MODE_VOL1 = [netapp_api.NaElement(
    etree.XML("""<volume-info xmlns="http://www.netapp.com/filer/admin">
    <name>open123</name>
    <state>online</state>
    <size-total>0</size-total>
    <size-used>0</size-used>
    <size-available>0</size-available>
    <is-inconsistent>false</is-inconsistent>
    <is-invalid>false</is-invalid>
    </volume-info>"""))]

FAKE_7MODE_POOLS = [
    {
        'pool_name': 'open123',
        'consistencygroup_support': True,
        'QoS_support': False,
        'reserved_percentage': 0,
        'total_capacity_gb': 0.0,
        'free_capacity_gb': 0.0,
        'max_over_subscription_ratio': 20.0,
        'multiattach': False,
        'thin_provisioning_support': False,
        'thick_provisioning_support': True,
        'utilization': 30.0,
        'filter_function': 'filter',
        'goodness_function': 'goodness',
    }
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


class test_snapshot(object):
    pass

    def __getitem__(self, key):
        return getattr(self, key)

test_snapshot = test_snapshot()
test_snapshot.id = 'fake_snap_id'
test_snapshot.name = 'snapshot-%s' % test_snapshot.id
test_snapshot.volume_id = 'fake_volume_id'
test_snapshot.provider_location = PROVIDER_LOCATION


def get_fake_net_interface_get_iter_response():
    return etree.XML("""<results status="passed">
        <num-records>1</num-records>
        <attributes-list>
            <net-interface-info></net-interface-info>
            <address>FAKE_IP</address>
        </attributes-list>
    </results>""")


def get_fake_ifs():
    list_of_ifs = [
        etree.XML("""<net-interface-info>
        <address>FAKE_IP</address></net-interface-info>"""),
        etree.XML("""<net-interface-info>
        <address>FAKE_IP2</address></net-interface-info>"""),
        etree.XML("""<net-interface-info>
        <address>FAKE_IP3</address></net-interface-info>"""),
    ]
    return [netapp_api.NaElement(el) for el in list_of_ifs]
