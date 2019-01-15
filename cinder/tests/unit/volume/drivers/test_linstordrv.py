# Copyright (c) 2018 LINBIT HA Solutions GmbH
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

import mock

from oslo_config import cfg
from oslo_utils import timeutils

from cinder import exception as cinder_exception
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers import linstordrv as drv

CONF = cfg.CONF

CINDER_UNKNOWN = 'unknown'
LVM = 'Lvm'
LVMTHIN = 'LvmThin'
DRIVER = 'cinder.volume.drivers.linstordrv.'

RESOURCE = {
    'name': 'CV_bc3015e6-695f-4688-91f2-1deb4321e4f0',
    'volume': {
        'device_path': '/dev/drbd1000',
    },
}

RESOURCE_LIST = {
    'resourceStates': [
        {
            'rscName': 'CV_bc3015e6-695f-4688-91f2-1deb4321e4f0',
            'nodeName': 'node_one',
            'inUse': False,
            'vlmStates': [
                {
                    'vlmNr': 0,
                    'diskState': 'Diskless',
                }
            ],
        },
        {
            'rscName': 'CV_bc3015e6-695f-4688-91f2-1deb4321e4f0',
            'nodeName': 'node_two',
            'inUse': False,
            'vlmStates': [
                {
                    'vlmNr': 0,
                    'diskState': 'UpToDate',
                }
            ],
        },
    ],
    'resources': [
        {
            'name': 'CV_bc3015e6-695f-4688-91f2-1deb4321e4f0',
            'nodeId': 0,
            'nodeName': 'node_one',
            'nodeUuid': '67939f68-2b26-41b7-b32e-a20b77664aef',
            'props': [{'key': 'PeerSlots', 'value': '7'}],
            'rscDfnUuid': '03623665-35a3-4caa-aa92-0c8badbda84a',
            'uuid': '559a229e-2b97-4d20-8f6d-87778bbe2f9e',
            'vlms': [
                {
                    'backingDisk': '/dev/vg-35/f1_00000',
                    'devicePath': '/dev/drbd1000',
                    'metaDisk': 'internal',
                    'storPoolName': 'DfltStorPool',
                    'storPoolUuid': 'd2f293f5-5d73-4447-a14b-70efe01302be',
                    'vlmDfnUuid': '0eedabe4-3c20-4eff-af74-b2ec2304ab0c',
                    'vlmMinorNr': 1000,
                    'vlmNr': 0,
                    'vlmUuid': '38e48fb8-e0af-4317-8aab-aabb46db4cf8'
                }
            ]
        },
        {
            'name': 'CV_bc3015e6-695f-4688-91f2-1deb4321e4f0',
            'nodeId': 1,
            'nodeName': 'node_two',
            'nodeUuid': '82c4c5a5-8290-481e-9e35-1c71094b0cab',
            'props': [{'key': 'PeerSlots', 'value': '7'}],
            'rscDfnUuid': '03623665-35a3-4caa-aa92-0c8badbda84a',
            'rscFlags': ['DISKLESS'],
            'uuid': '23d3d331-ad0c-43f3-975b-d1048e09dc23',
            'vlms': [
                {
                    'backingDisk': 'none',
                    'devicePath': '/dev/drbd1000',
                    'metaDisk': 'internal',
                    'storPoolName': 'DfltStorPool',
                    'storPoolUuid': '85ef7894-0682-4019-b95a-1b25e81c0cb5',
                    'vlmDfnUuid': '0eedabe4-3c20-4eff-af74-b2ec2304ab0c',
                    'vlmMinorNr': 1000,
                    'vlmNr': 0,
                    'vlmUuid': 'd25b6c91-680f-4aa6-97c3-533e4bf4e659'
                }
            ]
        }
    ]
}

RESOURCE_LIST_RESP = ['node_two', 'node_one']

SNAPSHOT_LIST_RESP = ['node_two']

RESOURCE_DFN_LIST = {
    'rscDfns': [
        {
            'rscDfnPort': 7002,
            'rscDfnProps': [{'key': u'DrbdPrimarySetOn',
                             'value': u'NODE_TWO'}],
            'rscDfnSecret': u'syxflfoMqj84cUUcsqta',
            'rscDfnUuid': u'f55f0c28-455b-458f-a05d-b5f7f16b5c22',
            'rscName': u'CV_bc3015e6-695f-4688-91f2-1deb4321e4f0',
            'vlmDfns': [
                {
                    'vlmDfnUuid': u'89f6eff2-c4cd-4586-9ab8-8e850568b93b',
                    'vlmMinor': 1001,
                    'vlmNr': 0,
                    'vlmProps': [{'key': u'DrbdCurrentGi',
                                  'value': u'2286D24524D26AA'}],
                    'vlmSize': '1044480'}
            ]
        },
    ]
}

RESOURCE_DFN_LIST_RESP = [
    {
        'rd_name': u'CV_bc3015e6-695f-4688-91f2-1deb4321e4f0',
        'rd_port': 7002,
        'rd_size': 1.0,
        'rd_uuid': u'f55f0c28-455b-458f-a05d-b5f7f16b5c22',
        'vlm_dfn_uuid': u'89f6eff2-c4cd-4586-9ab8-8e850568b93b'
    }
]

NODES_LIST = {
    'nodes': [
        {
            'connectionStatus': 2,
            'name': u'node_two',
            'netInterfaces': [
                {
                    'address': u'192.168.66.113',
                    'name': u'default',
                    'stltEncryptionType': u'PLAIN',
                    'stltPort': 3366,
                    'uuid': u'224e50c3-09a8-4cf8-b701-13663a66aecd'
                }
            ],
            'props': [{'key': u'CurStltConnName', 'value': u'default'}],
            'type': u'COMBINED',
            'uuid': u'67939f68-2b26-41b7-b32e-a20b77664aef'
        },
        {
            'connectionStatus': 2,
            'name': u'node_one',
            'netInterfaces': [
                {
                    'address': u'192.168.66.115',
                    'name': u'default',
                    'stltEncryptionType': u'PLAIN',
                    'stltPort': 3366,
                    'uuid': u'36f42ec9-9999-4ad7-a889-8d7dbb498163'
                }
            ],
            'props': [{'key': u'CurStltConnName', 'value': u'default'}],
            'type': u'COMBINED',
            'uuid': u'82c4c5a5-8290-481e-9e35-1c71094b0cab'
        }
    ]
}

NODES_RESP = [
    {
        'node_address': u'192.168.66.113',
        'node_name': u'node_two',
        'node_uuid': u'67939f68-2b26-41b7-b32e-a20b77664aef'
    },
    {
        'node_address': u'192.168.66.115',
        'node_name': u'node_one',
        'node_uuid': u'82c4c5a5-8290-481e-9e35-1c71094b0cab'
    }
]

STORAGE_POOL_DEF = {
    'storPoolDfns': [
        {
            'storPoolName': u'DfltStorPool',
            'uuid': u'f51611c6-528f-4793-a87a-866d09e6733a'
        }
    ]
}

STORAGE_POOL_DEF_RESP = [
    {
        'spd_name': u'DfltStorPool',
        'spd_uuid': u'f51611c6-528f-4793-a87a-866d09e6733a'
    }
]

STORAGE_POOL_LIST = {
    'storPools': [
        {
            'driver': u'LvmThinDriver',
            'freeSpace': {
                'freeCapacity': '36700160',
                'storPoolName': u'DfltStorPool',
                'storPoolUuid': u'd2f293f5-5d73-4447-a14b-70efe01302be',
                'totalCapacity': '36700160'
            },
            'nodeName': u'node_two',
            'nodeUuid': u'67939f68-2b26-41b7-b32e-a20b77664aef',
            'props': [{'key': u'StorDriver/LvmVg', 'value': u'vg-35'},
                      {'key': u'StorDriver/ThinPool',
                       'value': u'thinpool'}],
            'staticTraits': [{'key': u'Provisioning', 'value': u'Thin'},
                             {'key': u'SupportsSnapshots',
                              'value': u'true'}],
            'storPoolDfnUuid': u'f51611c6-528f-4793-a87a-866d09e6733a',
            'storPoolName': u'DfltStorPool',
            'storPoolUuid': u'd2f293f5-5d73-4447-a14b-70efe01302be',
            'vlms': [
                {
                    'backingDisk':
                        u'/dev/vg-35/CV_bc3015e6-695f-4688-91f2-1deb4321e4f0',
                    'devicePath': u'/dev/drbd1001',
                    'metaDisk': u'internal',
                    'storPoolName': u'DfltStorPool',
                    'storPoolUuid': u'd2f293f5-5d73-4447-a14b-70efe01302be',
                    'vlmDfnUuid': u'89f6eff2-c4cd-4586-9ab8-8e850568b93b',
                    'vlmMinorNr': 1001,
                    'vlmNr': 0,
                    'vlmUuid': u'b91392ae-904a-4bc6-862f-9c7aca629b35'
                },
                {
                    'backingDisk': u'/dev/vg-35/f1_00000',
                    'devicePath': u'/dev/drbd1000',
                    'metaDisk': u'internal',
                    'storPoolName': u'DfltStorPool',
                    'storPoolUuid': u'd2f293f5-5d73-4447-a14b-70efe01302be',
                    'vlmDfnUuid': u'0eedabe4-3c20-4eff-af74-b2ec2304ab0c',
                    'vlmMinorNr': 1000,
                    'vlmNr': 0,
                    'vlmUuid': u'38e48fb8-e0af-4317-8aab-aabb46db4cf8'
                }
            ]
        },
        {
            'driver': u'DisklessDriver',
            'freeSpace': {
                'freeCapacity': '9223372036854775807',
                'storPoolName': u'DfltStorPool',
                'storPoolUuid': u'85ef7894-0682-4019-b95a-1b25e81c0cb5',
                'totalCapacity': '9223372036854775807'
            },
            'nodeName': u'node_one',
            'nodeUuid': u'82c4c5a5-8290-481e-9e35-1c71094b0cab',
            'staticTraits': [{'key': u'SupportsSnapshots',
                              'value': u'false'}],
            'storPoolDfnUuid': u'f51611c6-528f-4793-a87a-866d09e6733a',
            'storPoolName': u'DfltStorPool',
            'storPoolUuid': u'85ef7894-0682-4019-b95a-1b25e81c0cb5',
            'vlms': [
                {
                    'backingDisk': u'none',
                    'devicePath': u'/dev/drbd1001',
                    'metaDisk': u'internal',
                    'storPoolName': u'DfltStorPool',
                    'storPoolUuid': u'85ef7894-0682-4019-b95a-1b25e81c0cb5',
                    'vlmDfnUuid': u'89f6eff2-c4cd-4586-9ab8-8e850568b93b',
                    'vlmMinorNr': 1001,
                    'vlmNr': 0,
                    'vlmUuid': u'4c63ee46-acb0-4aa5-8758-8fa8f65fdd5a'
                },
                {
                    'backingDisk': u'none',
                    'devicePath': u'/dev/drbd1000',
                    'metaDisk': u'internal',
                    'storPoolName': u'DfltStorPool',
                    'storPoolUuid': u'85ef7894-0682-4019-b95a-1b25e81c0cb5',
                    'vlmDfnUuid': u'0eedabe4-3c20-4eff-af74-b2ec2304ab0c',
                    'vlmMinorNr': 1000,
                    'vlmNr': 0,
                    'vlmUuid': u'd25b6c91-680f-4aa6-97c3-533e4bf4e659'
                }
            ]
        }
    ]
}

STORAGE_POOL_LIST_RESP = [
    {
        'driver_name': 'LvmThin',
        'node_name': u'node_two',
        'node_uuid': u'67939f68-2b26-41b7-b32e-a20b77664aef',
        'sp_cap': 35.0,
        'sp_free': 35.0,
        'sp_name': u'DfltStorPool',
        'sp_uuid': u'd2f293f5-5d73-4447-a14b-70efe01302be',
        'sp_vlms_uuid': [u'89f6eff2-c4cd-4586-9ab8-8e850568b93b',
                         u'0eedabe4-3c20-4eff-af74-b2ec2304ab0c']
    },
    {
        'driver_name': u'DisklessDriver',
        'node_name': u'node_one',
        'node_uuid': u'82c4c5a5-8290-481e-9e35-1c71094b0cab',
        'sp_cap': 0.0,
        'sp_free': -1.0,
        'sp_name': u'DfltStorPool',
        'sp_uuid': u'85ef7894-0682-4019-b95a-1b25e81c0cb5',
        'sp_vlms_uuid': [u'89f6eff2-c4cd-4586-9ab8-8e850568b93b',
                         u'0eedabe4-3c20-4eff-af74-b2ec2304ab0c']
    }
]

VOLUME_LIST = {
    'resourceStates': [
        {
            'inUse': False,
            'nodeName': u'wp-u16-cinder-dev-lg',
            'rscName': u'CV_bc3015e6-695f-4688-91f2-1deb4321e4f0',
            'vlmStates': [{'diskState': u'Diskless', 'vlmNr': 0}]
        },
        {
            'nodeName': u'wp-u16-cinder-dev-1', 'rscName': u'foo'
        },
        {
            'inUse': False,
            'nodeName': u'wp-u16-cinder-dev-1',
            'rscName': u'CV_bc3015e6-695f-4688-91f2-1deb4321e4f0',
            'vlmStates': [{'diskState': u'UpToDate', 'vlmNr': 0}]
        }
    ],
    'resources': [
        {
            'name': u'CV_bc3015e6-695f-4688-91f2-1deb4321e4f0',
            'nodeId': 0,
            'nodeName': u'wp-u16-cinder-dev-1',
            'nodeUuid': u'67939f68-2b26-41b7-b32e-a20b77664aef',
            'props': [{'key': u'PeerSlots', 'value': u'7'}],
            'rscDfnUuid': u'f55f0c28-455b-458f-a05d-b5f7f16b5c22',
            'uuid': u'2da61a7a-83b7-41d1-8a96-3a1a118dfba2',
            'vlms': [
                {
                    'backingDisk':
                        u'/dev/vg-35/CV_bc3015e6-695f-4688-91f2-' +
                        u'1deb4321e4f0_00000',
                    'devicePath': u'/dev/drbd1001',
                    'metaDisk': u'internal',
                    'storPoolName': u'DfltStorPool',
                    'storPoolUuid': u'd2f293f5-5d73-4447-a14b-70efe01302be',
                    'vlmDfnUuid': u'89f6eff2-c4cd-4586-9ab8-8e850568b93b',
                    'vlmMinorNr': 1001,
                    'vlmNr': 0,
                    'vlmUuid': u'b91392ae-904a-4bc6-862f-9c7aca629b35'
                }
            ]
        },
        {
            'name': u'CV_bc3015e6-695f-4688-91f2-1deb4321e4f0',
            'nodeId': 1,
            'nodeName': u'wp-u16-cinder-dev-lg',
            'nodeUuid': u'82c4c5a5-8290-481e-9e35-1c71094b0cab',
            'props': [{'key': u'PeerSlots', 'value': u'7'}],
            'rscDfnUuid': u'f55f0c28-455b-458f-a05d-b5f7f16b5c22',
            'rscFlags': [u'DISKLESS'],
            'uuid': u'bd6472d1-dc3c-4d41-a5f0-f44271c05680',
            'vlms': [
                {
                    'backingDisk': u'none',
                    'devicePath': u'/dev/drbd1001',
                    'metaDisk': u'internal',
                    'storPoolName': u'DfltStorPool',
                    'storPoolUuid': u'85ef7894-0682-4019-b95a-1b25e81c0cb5',
                    'vlmDfnUuid': u'89f6eff2-c4cd-4586-9ab8-8e850568b93b',
                    'vlmMinorNr': 1001,
                    'vlmNr': 0,
                    'vlmUuid': u'4c63ee46-acb0-4aa5-8758-8fa8f65fdd5a'
                }
            ]
        }
    ]
}

VOLUME_LIST_RESP = [
    {
        'node_name': u'wp-u16-cinder-dev-1',
        'rd_name': u'CV_bc3015e6-695f-4688-91f2-1deb4321e4f0',
        'volume': [
            {
                'backingDisk': u'/dev/vg-35/CV_bc3015e6-695f-4688-91f2-' +
                               u'1deb4321e4f0_00000',
                'devicePath': u'/dev/drbd1001',
                'metaDisk': u'internal',
                'storPoolName': u'DfltStorPool',
                'storPoolUuid': u'd2f293f5-5d73-4447-a14b-70efe01302be',
                'vlmDfnUuid': u'89f6eff2-c4cd-4586-9ab8-8e850568b93b',
                'vlmMinorNr': 1001,
                'vlmNr': 0,
                'vlmUuid': u'b91392ae-904a-4bc6-862f-9c7aca629b35'
            }
        ]
    },
    {
        'node_name': u'wp-u16-cinder-dev-lg',
        'rd_name': u'CV_bc3015e6-695f-4688-91f2-1deb4321e4f0',
        'volume': [
            {
                'backingDisk': u'none',
                'devicePath': u'/dev/drbd1001',
                'metaDisk': u'internal',
                'storPoolName': u'DfltStorPool',
                'storPoolUuid': u'85ef7894-0682-4019-b95a-1b25e81c0cb5',
                'vlmDfnUuid': u'89f6eff2-c4cd-4586-9ab8-8e850568b93b',
                'vlmMinorNr': 1001,
                'vlmNr': 0,
                'vlmUuid': u'4c63ee46-acb0-4aa5-8758-8fa8f65fdd5a'
            }
        ]
    }
]

VOLUME_STATS_RESP = {
    'driver_version': '0.0.7',
    'pools': [
        {
            'QoS_support': False,
            'backend_state': 'up',
            'filter_function': None,
            'free_capacity_gb': 35.0,
            'goodness_function': None,
            'location_info': 'linstor://localhost',
            'max_over_subscription_ratio': 0,
            'multiattach': False,
            'pool_name': 'lin-test-driver',
            'provisioned_capacity_gb': 1.0,
            'reserved_percentage': 0,
            'thick_provisioning_support': False,
            'thin_provisioning_support': True,
            'total_capacity_gb': 35.0,
            'total_volumes': 1,
        }
    ],
    'vendor_name': 'LINBIT',
    'volume_backend_name': 'lin-test-driver'
}

CINDER_VOLUME = {
    'id': 'bc3015e6-695f-4688-91f2-1deb4321e4f0',
    'name': 'test-lin-vol',
    'size': 1,
    'volume_type_id': 'linstor',
    'created_at': timeutils.utcnow()
}

SNAPSHOT = {
    'id': 'bc3015e6-695f-4688-91f2-1deb4321e4f0',
    'volume_id': 'bc3015e6-695f-4688-91f2-1deb4321e4f0',
    'volume_size': 1
}

VOLUME_NAMES = {
    'linstor': 'CV_bc3015e6-695f-4688-91f2-1deb4321e4f0',
    'cinder': 'bc3015e6-695f-4688-91f2-1deb4321e4f0',
    'snap': 'SN_bc3015e6-695f-4688-91f2-1deb4321e4f0',
}


class LinstorAPIFakeDriver(object):

    def fake_api_ping(self):
        return 1234

    def fake_api_resource_list(self):
        return RESOURCE_LIST

    def fake_api_node_list(self):
        return NODES_LIST

    def fake_api_storage_pool_dfn_list(self):
        return STORAGE_POOL_DEF

    def fake_api_storage_pool_list(self):
        return STORAGE_POOL_LIST

    def fake_api_volume_list(self):
        return VOLUME_LIST

    def fake_api_resource_dfn_list(self):
        return RESOURCE_DFN_LIST

    def fake_api_snapshot_list(self):
        return SNAPSHOT_LIST_RESP


class LinstorBaseDriverTestCase(test.TestCase):

    def __init__(self, *args, **kwargs):
        super(LinstorBaseDriverTestCase, self).__init__(*args, **kwargs)

    def setUp(self):
        super(LinstorBaseDriverTestCase, self).setUp()

        if drv is None:
            return

        self._mock = mock.Mock()
        self._fake_driver = LinstorAPIFakeDriver()

        self.configuration = mock.Mock(conf.Configuration)

        self.driver = drv.LinstorBaseDriver(
            configuration=self.configuration)
        self.driver.VERSION = '0.0.7'
        self.driver.default_rsc_size = 1
        self.driver.default_vg_name = 'vg-1'
        self.driver.default_downsize_factor = int('4096')
        self.driver.default_pool = STORAGE_POOL_DEF_RESP[0]['spd_name']
        self.driver.host_name = 'node_one'
        self.driver.diskless = True
        self.driver.default_uri = 'linstor://localhost'
        self.driver.default_backend_name = 'lin-test-driver'
        self.driver.configuration.reserved_percentage = 0
        self.driver.configuration.max_over_subscription_ratio = 0

    @mock.patch(DRIVER + 'LinstorBaseDriver._ping')
    def test_ping(self, m_ping):
        m_ping.return_value = self._fake_driver.fake_api_ping()

        val = self.driver._ping()
        expected = 1234
        self.assertEqual(expected, val)

    @mock.patch('uuid.uuid4')
    def test_clean_uuid(self, m_uuid):
        m_uuid.return_value = u'bd6472d1-dc3c-4d41-a5f0-f44271c05680'

        val = self.driver._clean_uuid()
        expected = u'bd6472d1-dc3c-4d41-a5f0-f44271c05680'
        self.assertEqual(expected, val)

    # Test volume size conversions
    def test_unit_conversions_to_linstor(self):
        val = self.driver._vol_size_to_linstor(1)
        expected = 1044480   # 1048575 - 4096
        self.assertEqual(expected, val)

    def test_unit_conversions_to_cinder(self):
        val = self.driver._vol_size_to_cinder(1048576)
        expected = 1
        self.assertEqual(expected, val)

    def test_is_clean_volume_name(self):
        val = self.driver._is_clean_volume_name(VOLUME_NAMES['cinder'],
                                                drv.DM_VN_PREFIX)
        expected = VOLUME_NAMES['linstor']
        self.assertEqual(expected, val)

    def test_snapshot_name_from_cinder_snapshot(self):
        val = self.driver._snapshot_name_from_cinder_snapshot(
            SNAPSHOT)
        expected = VOLUME_NAMES['snap']
        self.assertEqual(expected, val)

    def test_cinder_volume_name_from_drbd_resource(self):
        val = self.driver._cinder_volume_name_from_drbd_resource(
            VOLUME_NAMES['linstor'])
        expected = VOLUME_NAMES['cinder']
        self.assertEqual(expected, val)

    def test_drbd_resource_name_from_cinder_snapshot(self):
        val = self.driver._drbd_resource_name_from_cinder_snapshot(
            SNAPSHOT)
        expected = VOLUME_NAMES['linstor']
        self.assertEqual(expected, val)

    def test_drbd_resource_name_from_cinder_volume(self):
        val = self.driver._drbd_resource_name_from_cinder_volume(
            CINDER_VOLUME)
        expected = VOLUME_NAMES['linstor']
        self.assertEqual(expected, val)

    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_resource_list')
    def test_get_rcs_path(self, m_rsc_list):
        m_rsc_list.return_value = self._fake_driver.fake_api_resource_list()

        val = self.driver._get_rsc_path(VOLUME_NAMES['linstor'])
        expected = '/dev/drbd1000'
        self.assertEqual(expected, val)

    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_resource_list')
    def test_get_local_path(self, m_rsc_list):
        m_rsc_list.return_value = self._fake_driver.fake_api_resource_list()

        val = self.driver._get_local_path(CINDER_VOLUME)
        expected = '/dev/drbd1000'
        self.assertEqual(expected, val)

    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_storage_pool_dfn_list')
    def test_get_spd(self, m_spd_list):
        m_spd_list.return_value = (
            self._fake_driver.fake_api_storage_pool_dfn_list())

        val = self.driver._get_spd()
        expected = STORAGE_POOL_DEF_RESP
        self.assertEqual(expected, val)

    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_storage_pool_list')
    def test_get_storage_pool(self, m_sp_list):
        m_sp_list.return_value = (
            self._fake_driver.fake_api_storage_pool_list())

        val = self.driver._get_storage_pool()
        expected = STORAGE_POOL_LIST_RESP
        self.assertEqual(expected, val)

    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_resource_dfn_list')
    def test_get_resource_definitions(self, m_rscd_list):
        m_rscd_list.return_value = (
            self._fake_driver.fake_api_resource_dfn_list())

        val = self.driver._get_resource_definitions()
        expected = RESOURCE_DFN_LIST_RESP
        self.assertEqual(expected, val)

    @mock.patch(DRIVER + 'LinstorBaseDriver._get_snapshot_nodes')
    def test_get_snapshot_nodes(self, m_rsc_list):
        m_rsc_list.return_value = self._fake_driver.fake_api_snapshot_list()

        val = self.driver._get_snapshot_nodes(VOLUME_NAMES['linstor'])
        expected = SNAPSHOT_LIST_RESP
        self.assertEqual(expected, val)

    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_nodes_list')
    def test_get_linstor_nodes(self, m_node_list):
        m_node_list.return_value = self._fake_driver.fake_api_node_list()

        val = self.driver._get_linstor_nodes()
        expected = RESOURCE_LIST_RESP
        self.assertEqual(expected, val)

    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_nodes_list')
    def test_get_nodes(self, m_node_list):
        m_node_list.return_value = self._fake_driver.fake_api_node_list()

        val = self.driver._get_nodes()
        expected = NODES_RESP
        self.assertEqual(expected, val)

    @mock.patch(DRIVER + 'LinstorBaseDriver.get_goodness_function')
    @mock.patch(DRIVER + 'LinstorBaseDriver.get_filter_function')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_resource_dfn_list')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_storage_pool_list')
    def test_get_volume_stats(self,
                              m_sp_list,
                              m_rscd_list,
                              m_filter,
                              m_goodness):
        m_sp_list.return_value = (
            self._fake_driver.fake_api_storage_pool_list())
        m_rscd_list.return_value = (
            self._fake_driver.fake_api_resource_dfn_list())
        m_filter.return_value = None
        m_goodness.return_value = None

        val = self.driver._get_volume_stats()
        expected = VOLUME_STATS_RESP
        self.assertEqual(expected, val)

    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_resource_list')
    @mock.patch(DRIVER + 'LinstorBaseDriver._check_api_reply')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_snapshot_create')
    def test_create_snapshot_fail(self,
                                  m_snap_create,
                                  m_api_reply,
                                  m_rsc_list):
        m_snap_create.return_value = None
        m_rsc_list.return_value = self._fake_driver.fake_api_resource_list()
        m_api_reply.return_value = False

        self.assertRaises(cinder_exception.VolumeBackendAPIException,
                          self.driver.create_snapshot, SNAPSHOT)

    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_resource_list')
    @mock.patch(DRIVER + 'LinstorBaseDriver._check_api_reply')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_snapshot_create')
    def test_create_snapshot_success(self,
                                     m_snap_create,
                                     m_api_reply,
                                     m_rsc_list):
        m_snap_create.return_value = None
        m_rsc_list.return_value = self._fake_driver.fake_api_resource_list()
        m_api_reply.return_value = True

        # No exception should be raised
        self.assertIsNone(self.driver.create_snapshot(SNAPSHOT))

    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_resource_dfn_list')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_resource_list')
    @mock.patch(DRIVER + 'LinstorBaseDriver._check_api_reply')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_snapshot_delete')
    def test_delete_snapshot_fail(self,
                                  m_snap_delete,
                                  m_api_reply,
                                  m_rsc_list,
                                  m_rsc_dfn_list):
        m_snap_delete.return_value = None
        m_api_reply.return_value = False
        m_rsc_list.return_value = self._fake_driver.fake_api_resource_list()
        m_rsc_dfn_list.return_value = (
            self._fake_driver.fake_api_resource_dfn_list())

        self.assertRaises(cinder_exception.VolumeBackendAPIException,
                          self.driver.delete_snapshot, SNAPSHOT)

    @mock.patch(DRIVER + 'LinstorBaseDriver._api_rsc_dfn_delete')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_resource_list')
    @mock.patch(DRIVER + 'LinstorBaseDriver._check_api_reply')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_snapshot_delete')
    def test_delete_snapshot_success(self,
                                     m_snap_delete,
                                     m_api_reply,
                                     m_rsc_list,
                                     m_rsc_dfn_delete):
        m_snap_delete.return_value = None
        m_api_reply.return_value = True
        m_rsc_list.return_value = self._fake_driver.fake_api_resource_list()
        m_rsc_dfn_delete.return_value = True

        # No exception should be raised
        self.driver.delete_snapshot(SNAPSHOT)

    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_storage_pool_list')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_volume_dfn_set_sp')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_volume_extend')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_rsc_create')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_snapshot_resource_restore')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_linstor_nodes')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_snapshot_volume_dfn_restore')
    @mock.patch(DRIVER + 'LinstorBaseDriver._check_api_reply')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_rsc_dfn_create')
    def test_create_volume_from_snapshot(self,
                                         m_rsc_dfn_create,
                                         m_api_reply,
                                         m_snap_vd_restore,
                                         m_lin_nodes,
                                         m_snap_rsc_restore,
                                         m_rsc_create,
                                         m_vol_extend,
                                         m_vol_dfn,
                                         m_sp_list):
        m_rsc_dfn_create.return_value = True
        m_api_reply.return_value = True
        m_snap_vd_restore.return_value = True
        m_nodes = []
        m_nodes.append('for test')
        m_nodes.remove('for test')
        m_lin_nodes.return_value = m_nodes
        m_snap_rsc_restore.return_value = True
        m_rsc_create.return_value = True
        m_vol_extend.return_value = True
        m_vol_dfn.return_value = True
        m_sp_list.return_value = (
            self._fake_driver.fake_api_storage_pool_list())

        self.assertIsNone(self.driver.create_volume_from_snapshot(
            CINDER_VOLUME, SNAPSHOT))

    @mock.patch(DRIVER + 'LinstorBaseDriver._check_api_reply')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_rsc_create')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_volume_dfn_create')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_rsc_dfn_create')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_storage_pool_create')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_storage_pool_dfn_list')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_nodes_list')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_storage_pool_list')
    def test_create_volume_fail_no_linstor_nodes(self,
                                                 m_sp_list,
                                                 m_node_list,
                                                 m_spd_list,
                                                 m_sp_create,
                                                 m_rsc_dfn_create,
                                                 m_vol_dfn_create,
                                                 m_rsc_create,
                                                 m_api_reply):
        m_sp_list.return_value = []
        m_node_list.return_value = []
        m_spd_list.return_value = (
            self._fake_driver.fake_api_storage_pool_dfn_list())
        m_sp_create.return_value = True
        m_rsc_dfn_create.return_value = True
        m_vol_dfn_create.return_value = True
        m_rsc_create.return_value = True
        m_api_reply.return_value = True

        test_volume = CINDER_VOLUME
        test_volume['migration_status'] = ('migrating:',
                                           str(VOLUME_NAMES['cinder']))
        test_volume['display_name'] = 'test_volume'
        test_volume['host'] = 'node_one'
        test_volume['size'] = 1

        self.assertRaises(cinder_exception.VolumeBackendAPIException,
                          self.driver.create_volume, test_volume)

    @mock.patch(DRIVER + 'LinstorBaseDriver._check_api_reply')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_rsc_create')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_volume_dfn_create')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_rsc_dfn_create')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_storage_pool_create')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_storage_pool_dfn_list')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_nodes_list')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_storage_pool_list')
    def test_create_volume_fail_rsc_create(self,
                                           m_sp_list,
                                           m_node_list,
                                           m_spd_list,
                                           m_sp_create,
                                           m_rsc_dfn_create,
                                           m_vol_dfn_create,
                                           m_rsc_create,
                                           m_api_reply):
        m_sp_list.return_value = (
            self._fake_driver.fake_api_storage_pool_list())
        m_node_list.return_value = self._fake_driver.fake_api_node_list()
        m_spd_list.return_value = (
            self._fake_driver.fake_api_storage_pool_dfn_list())
        m_sp_create.return_value = True
        m_rsc_dfn_create.return_value = True
        m_vol_dfn_create.return_value = True
        m_rsc_create.return_value = True
        m_api_reply.return_value = False

        test_volume = CINDER_VOLUME
        test_volume['migration_status'] = ('migrating:',
                                           str(VOLUME_NAMES['cinder']))
        test_volume['display_name'] = 'test_volume'
        test_volume['host'] = 'node_one'
        test_volume['size'] = 1

        self.assertRaises(cinder_exception.VolumeBackendAPIException,
                          self.driver.create_volume, test_volume)

    @mock.patch(DRIVER + 'LinstorBaseDriver._check_api_reply')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_rsc_create')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_volume_dfn_create')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_rsc_dfn_create')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_storage_pool_create')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_storage_pool_dfn_list')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_nodes_list')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_storage_pool_list')
    def test_create_volume(self,
                           m_sp_list,
                           m_node_list,
                           m_spd_list,
                           m_sp_create,
                           m_rsc_dfn_create,
                           m_vol_dfn_create,
                           m_rsc_create,
                           m_api_reply):
        m_sp_list.return_value = (
            self._fake_driver.fake_api_storage_pool_list())
        m_node_list.return_value = self._fake_driver.fake_api_node_list()
        m_spd_list.return_value = (
            self._fake_driver.fake_api_storage_pool_dfn_list())
        m_sp_create.return_value = True
        m_rsc_dfn_create.return_value = True
        m_vol_dfn_create.return_value = True
        m_rsc_create.return_value = True
        m_api_reply.return_value = True

        test_volume = CINDER_VOLUME
        test_volume['migration_status'] = ('migrating:',
                                           str(VOLUME_NAMES['cinder']))
        test_volume['display_name'] = 'test_volume'
        test_volume['host'] = 'node_one'
        test_volume['size'] = 1

        val = self.driver.create_volume(test_volume)
        expected = {}
        self.assertEqual(val, expected)

    @mock.patch(DRIVER + 'LinstorBaseDriver._check_api_reply')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_rsc_dfn_delete')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_volume_dfn_delete')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_rsc_delete')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_resource_list')
    def test_delete_volume_fail_incomplete(self,
                                           m_rsc_list,
                                           m_rsc_delete,
                                           m_vol_dfn_delete,
                                           m_rsc_dfn_delete,
                                           m_api_reply):
        m_rsc_list.return_value = self._fake_driver.fake_api_resource_list()
        m_rsc_delete.return_value = True
        m_vol_dfn_delete.return_value = True
        m_rsc_dfn_delete.return_value = True
        m_api_reply.return_value = False

        test_volume = CINDER_VOLUME
        test_volume['display_name'] = 'linstor_test'
        test_volume['host'] = 'node_one'
        test_volume['size'] = 1

        self.assertRaises(cinder_exception.VolumeBackendAPIException,
                          self.driver.delete_volume, test_volume)

    @mock.patch(DRIVER + 'LinstorBaseDriver._check_api_reply')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_rsc_dfn_delete')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_volume_dfn_delete')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_rsc_delete')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_resource_list')
    def test_delete_volume(self,
                           m_rsc_list,
                           m_rsc_delete,
                           m_vol_dfn_delete,
                           m_rsc_dfn_delete,
                           m_api_reply):
        m_rsc_list.return_value = self._fake_driver.fake_api_resource_list()
        m_rsc_delete.return_value = True
        m_vol_dfn_delete.return_value = True
        m_rsc_dfn_delete.return_value = True
        m_api_reply.return_value = True

        test_volume = CINDER_VOLUME
        test_volume['display_name'] = 'linstor_test'
        test_volume['host'] = 'node_one'
        test_volume['size'] = 1

        val = self.driver.delete_volume(test_volume)
        expected = True
        self.assertEqual(val, expected)

    @mock.patch(DRIVER + 'LinstorBaseDriver._check_api_reply')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_volume_extend')
    def test_extend_volume_success(self, m_vol_extend, m_api_reply):
        m_vol_extend.return_value = True
        m_api_reply.return_value = True

        # No exception should be raised
        self.driver.extend_volume(CINDER_VOLUME, 2)

    @mock.patch(DRIVER + 'LinstorBaseDriver._check_api_reply')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_volume_extend')
    def test_extend_volume_fail(self, m_vol_extend, m_api_reply):
        m_vol_extend.return_value = False
        m_api_reply.return_value = False

        self.assertRaises(cinder_exception.VolumeBackendAPIException,
                          self.driver.extend_volume,
                          CINDER_VOLUME,
                          2)

    def test_migrate_volume(self):
        m_ctxt = {}
        m_volume = {}
        m_host = ''

        val = self.driver.migrate_volume(m_ctxt, m_volume, m_host)
        expected = (False, None)
        self.assertEqual(val, expected)


class LinstorIscsiDriverTestCase(test.TestCase):

    def __init__(self, *args, **kwargs):
        super(LinstorIscsiDriverTestCase, self).__init__(*args, **kwargs)

    def setUp(self):
        super(LinstorIscsiDriverTestCase, self).setUp()

        self._mock = mock.Mock()
        self._fake_driver = LinstorAPIFakeDriver()

        self.configuration = mock.Mock(conf.Configuration)
        self.configuration.iscsi_helper = 'tgtadm'
        self.driver = drv.LinstorIscsiDriver(
            configuration=self.configuration, h_name='tgtadm')

        self.driver.VERSION = '0.0.7'
        self.driver.default_rsc_size = 1
        self.driver.default_vg_name = 'vg-1'
        self.driver.default_downsize_factor = int('4096')
        self.driver.default_pool = STORAGE_POOL_DEF_RESP[0]['spd_name']
        self.driver.host_name = 'node_one'
        self.driver.diskless = True
        self.driver.location_info = 'LinstorIscsi:linstor://localhost'
        self.driver.default_backend_name = 'lin-test-driver'
        self.driver.configuration.reserved_percentage = int('0')
        self.driver.configuration.max_over_subscription_ratio = int('0')

    @mock.patch(DRIVER + 'LinstorIscsiDriver._get_volume_stats')
    def test_iscsi_get_volume_stats(self, m_vol_stats):

        m_vol_stats.return_value = VOLUME_STATS_RESP

        val = self.driver.get_volume_stats()

        expected = VOLUME_STATS_RESP
        expected["storage_protocol"] = 'iSCSI'
        self.assertEqual(val, expected)

    @mock.patch(DRIVER + 'proto')
    @mock.patch(DRIVER + 'linstor')
    def test_iscsi_check_for_setup_error_pass(self, m_linstor, m_proto):
        m_linstor.return_value = True
        m_proto.return_value = True

        # No exception should be raised
        self.driver.check_for_setup_error()


class LinstorDrbdDriverTestCase(test.TestCase):

    def __init__(self, *args, **kwargs):
        super(LinstorDrbdDriverTestCase, self).__init__(*args, **kwargs)

    def setUp(self):
        super(LinstorDrbdDriverTestCase, self).setUp()

        self._mock = mock.Mock()
        self._fake_driver = LinstorAPIFakeDriver()

        self.configuration = mock.Mock(conf.Configuration)
        self.driver = drv.LinstorDrbdDriver(
            configuration=self.configuration)

        self.driver.VERSION = '0.0.7'
        self.driver.default_rsc_size = 1
        self.driver.default_vg_name = 'vg-1'
        self.driver.default_downsize_factor = int('4096')
        self.driver.default_pool = STORAGE_POOL_DEF_RESP[0]['spd_name']
        self.driver.host_name = 'node_one'
        self.driver.diskless = True
        self.driver.location_info = 'LinstorDrbd:linstor://localhost'
        self.driver.default_backend_name = 'lin-test-driver'
        self.driver.configuration.reserved_percentage = int('0')
        self.driver.configuration.max_over_subscription_ratio = int('0')

    @mock.patch(DRIVER + 'LinstorDrbdDriver._get_rsc_path')
    def test_drbd_return_drbd_config(self, m_rsc_path):
        m_rsc_path.return_value = '/dev/drbd1000'

        val = self.driver._return_drbd_config(CINDER_VOLUME)

        expected = {
            'driver_volume_type': 'local',
            'data': {
                "device_path": str(m_rsc_path.return_value)
            }
        }
        self.assertEqual(val, expected)

    @mock.patch(DRIVER + 'LinstorDrbdDriver._get_api_storage_pool_list')
    def test_drbd_node_in_sp(self, m_sp_list):
        m_sp_list.return_value = (
            self._fake_driver.fake_api_storage_pool_list())

        val = self.driver._node_in_sp('node_two')
        self.assertTrue(val)

    @mock.patch(DRIVER + 'LinstorDrbdDriver._get_volume_stats')
    def test_drbd_get_volume_stats(self, m_vol_stats):
        m_vol_stats.return_value = VOLUME_STATS_RESP

        val = self.driver.get_volume_stats()
        expected = VOLUME_STATS_RESP
        expected["storage_protocol"] = 'DRBD'
        self.assertEqual(val, expected)

    @mock.patch(DRIVER + 'proto')
    @mock.patch(DRIVER + 'linstor')
    def test_drbd_check_for_setup_error_pass(self, m_linstor, m_proto):
        m_linstor.return_value = True
        m_proto.return_value = True

        # No exception should be raised
        self.driver.check_for_setup_error()

    @mock.patch(DRIVER + 'LinstorDrbdDriver._get_rsc_path')
    @mock.patch(DRIVER + 'LinstorDrbdDriver._check_api_reply')
    @mock.patch(DRIVER + 'LinstorDrbdDriver._api_rsc_create')
    @mock.patch(DRIVER + 'LinstorDrbdDriver._node_in_sp')
    def test_drbd_initialize_connection_pass(self,
                                             m_node_sp,
                                             m_rsc_create,
                                             m_check,
                                             m_rsc_path):
        m_node_sp.return_value = True
        m_rsc_create.return_value = True
        m_check.return_value = True
        m_rsc_path.return_value = '/dev/drbd1000'

        connector = {}
        connector["host"] = 'wp-u16-cinder-dev-lg'

        val = self.driver.initialize_connection(CINDER_VOLUME, connector)

        expected = {
            'driver_volume_type': 'local',
            'data': {
                "device_path": str(m_rsc_path.return_value)
            }
        }
        self.assertEqual(val, expected)

    @mock.patch(DRIVER + 'LinstorDrbdDriver._check_api_reply')
    @mock.patch(DRIVER + 'LinstorDrbdDriver._api_rsc_delete')
    @mock.patch(DRIVER + 'LinstorDrbdDriver._node_in_sp')
    def test_drbd_terminate_connection_pass(self,
                                            m_node_sp,
                                            m_rsc_create,
                                            m_check):
        m_node_sp.return_value = True
        m_rsc_create.return_value = True
        m_check.return_value = True

        connector = {}
        connector["host"] = 'wp-u16-cinder-dev-lg'

        # No exception should be raised
        self.driver.terminate_connection(CINDER_VOLUME, connector)
