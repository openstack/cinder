# Copyright (c) 2018-2019 LINBIT HA Solutions GmbH
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

from unittest import mock

from oslo_config import cfg
from oslo_utils import timeutils

from cinder import exception as cinder_exception
from cinder.tests.unit import test
from cinder.volume import configuration as conf
from cinder.volume.drivers import linstordrv as drv

CONF = cfg.CONF

CINDER_UNKNOWN = 'unknown'
DISKLESS = 'DISKLESS'
LVM = 'LVM'
LVM_THIN = 'LVM_THIN'
ZFS = 'ZFS'
ZFS_THIN = 'ZFS_THIN'
DRIVER = 'cinder.volume.drivers.linstordrv.'

RESOURCE = {
    'name': 'CV_0348a7d3-3bb9-452d-9f40-2cf5ebfe9131',
    'volume': {
        'device_path': '/dev/drbd1000'
    }
}

RESOURCE_LIST = [{
    'layer_object': {
        'children': [{
            'storage': {
                'storage_volumes': [{
                    'allocated_size_kib': 1048576,
                    'device_path':
                    '/dev/vol/CV_0348a7d3-3bb9-452d-9f40-2cf5ebfe9131_00000',
                    'disk_state': '[]',
                    'usable_size_kib': 1048576,
                    'volume_number': 0}]},
            'type': 'STORAGE'}],
        'drbd': {
            'al_size': 32,
            'al_stripes': 1,
            'drbd_resource_definition': {
                'al_stripe_size_kib': 32,
                'al_stripes': 1,
                'down': False,
                'peer_slots': 7,
                'port': 7005,
                'secret': 'poQZ0Ad/Bq8DT9fA7ydB',
                'transport_type': 'IP'},
            'drbd_volumes': [{
                'allocated_size_kib': 1044740,
                'backing_device':
                    '/dev/vol/CV_0348a7d3-3bb9-452d-9f40-2cf5ebfe9131_00000',
                'device_path': '/dev/drbd1005',
                'drbd_volume_definition': {
                    'minor_number': 1005,
                    'volume_number': 0},
                'usable_size_kib': 1044480}],
            'node_id': 0,
            'peer_slots': 7},
        'type': 'DRBD'},
    'name': 'CV_0348a7d3-3bb9-452d-9f40-2cf5ebfe9131',
    'node_name': 'node-2',
    'state': {'in_use': False},
    'uuid': 'a4ab4670-c5fc-4590-a3a2-39c4685c8c32',
    'volumes': [{
        'allocated_size_kib': 45403,
        'device_path': '/dev/drbd1005',
        'layer_data_list': [{
            'data': {
                'allocated_size_kib': 1044740,
                'backing_device':
                '/dev/vol/CV_0348a7d3-3bb9-452d-9f40-2cf5ebfe9131_00000',
                'device_path': '/dev/drbd1005',
                'drbd_volume_definition': {
                    'minor_number': 1005,
                    'volume_number': 0},
                'usable_size_kib': 1044480},
            'type': 'DRBD'}, {
            'data': {
                'allocated_size_kib': 1048576,
                'device_path':
                '/dev/vol/CV_0348a7d3-3bb9-452d-9f40-2cf5ebfe9131_00000',
                'disk_state': '[]',
                'usable_size_kib': 1048576,
                'volume_number': 0},
            'type': 'STORAGE'}
        ],
        'props': {
            'RestoreFromResource': 'CV_123a2fdc-365f-472e-bb8e-484788712abc',
            'RestoreFromSnapshot': 'SN_68edb708-48de-4da1-9953-b9de9da9f1b8'
        },
        'provider_kind': 'LVM_THIN',
        'state': {'disk_state': 'UpToDate'},
        'storage_pool_name': 'DfltStorPool',
        'uuid': 'e270ba0c-b284-4f21-85cc-602f132a2251',
        'volume_number': 0}]}, {
    'flags': ['DISKLESS'],
    'layer_object': {
        'children': [{
            'storage': {
                'storage_volumes': [{
                    'allocated_size_kib': 0,
                    'usable_size_kib': 1044480,
                    'volume_number': 0}]},
            'type': 'STORAGE'}],
        'drbd': {
            'al_size': 32,
            'al_stripes': 1,
            'drbd_resource_definition': {
                'al_stripe_size_kib': 32,
                'al_stripes': 1,
                'down': False,
                'peer_slots': 7,
                'port': 7005,
                'secret': 'poQZ0Ad/Bq8DT9fA7ydB',
                'transport_type': 'IP'},
            'drbd_volumes': [{
                'allocated_size_kib': 1044740,
                'device_path': '/dev/drbd1005',
                'drbd_volume_definition': {
                    'minor_number': 1005,
                    'volume_number': 0},
                'usable_size_kib': 1044480}],
            'flags': ['DISKLESS'],
            'node_id': 1,
            'peer_slots': 7},
        'type': 'DRBD'},
    'name': 'CV_0348a7d3-3bb9-452d-9f40-2cf5ebfe9131',
    'node_name': 'node-1',
    'state': {'in_use': False},
    'uuid': '11e853df-6f66-4cd9-9fbc-f3f7cc98d5cf',
    'volumes': [{
        'allocated_size_kib': 45403,
        'device_path': '/dev/drbd1005',
        'layer_data_list': [
            {
                'data': {
                    'allocated_size_kib': 1044740,
                    'device_path': '/dev/drbd1005',
                    'drbd_volume_definition': {
                        'minor_number': 1005,
                        'volume_number': 0},
                    'usable_size_kib': 1044480},
                'type': 'DRBD'
            },
            {
                'data': {
                    'allocated_size_kib': 0,
                    'usable_size_kib': 1044480,
                    'volume_number': 0
                },
                'type': 'STORAGE'
            }
        ],
        'provider_kind': 'DISKLESS',
        'state': {'disk_state': 'Diskless'},
        'storage_pool_name': 'DfltStorPool',
        'uuid': '27b4aeec-2b42-41c9-b186-86afc8778046',
        'volume_number': 0
    }]}]

RESOURCE_LIST_RESP = ['node-1', 'node-2']

SNAPSHOT_LIST_RESP = ['node-1']

DISKLESS_LIST_RESP = ['node-1']

RESOURCE_DFN_LIST = [{
    'layer_data': [
        {
            'data': {
                'al_stripe_size_kib': 32,
                'al_stripes': 1,
                'down': False,
                'peer_slots': 7,
                'port': 7005,
                'secret': 'poQZ0Ad/Bq8DT9fA7ydB',
                'transport_type': 'IP'
            },
            'type': 'DRBD'
        },
        {
            'type': 'STORAGE'
        }
    ],
    'name': 'CV_0348a7d3-3bb9-452d-9f40-2cf5ebfe9131',
    'props': {'DrbdPrimarySetOn': 'node-1'},
    'uuid': '9a684294-6db4-40c8-bfeb-e5351200b9db'
}]

RESOURCE_DFN_LIST_RESP = [{
    'rd_name': u'CV_0348a7d3-3bb9-452d-9f40-2cf5ebfe9131',
    'rd_uuid': u'9a684294-6db4-40c8-bfeb-e5351200b9db',
}]

NODES_LIST = [
    {
        'connection_status': 'ONLINE',
        'name': 'node-1',
        'net_interfaces': [{
            'address': '192.168.8.63',
            'name': 'default',
            'satellite_encryption_type': 'PLAIN',
            'satellite_port': 3366,
            'uuid': '9c5b727f-0c62-4040-9a33-96a4fd4aaac3'}],
        'props': {'CurStltConnName': 'default'},
        'type': 'COMBINED',
        'uuid': '69b88ffb-50d9-4576-9843-d7bf4724d043'
    },
    {
        'connection_status': 'ONLINE',
        'name': 'node-2',
        'net_interfaces': [{
            'address': '192.168.8.102',
            'name': 'default',
            'satellite_encryption_type': 'PLAIN',
            'satellite_port': 3366,
            'uuid': '3f911fc9-4f9b-4155-b9da-047d5242484c'}],
        'props': {'CurStltConnName': 'default'},
        'type': 'SATELLITE',
        'uuid': '26bde754-0f05-499c-a63c-9f4e5f30556e'
    }
]

NODES_RESP = [
    {'node_address': '192.168.8.63', 'node_name': 'node-1'},
    {'node_address': '192.168.8.102', 'node_name': 'node-2'}
]

STORAGE_POOL_DEF = [{'storage_pool_name': 'DfltStorPool'}]

STORAGE_POOL_DEF_RESP = ['DfltStorPool']

STORAGE_POOL_LIST = [
    {
        'free_capacity': 104815656,
        'free_space_mgr_name': 'node-2:DfltStorPool',
        'node_name': 'node-2',
        'props': {
            'StorDriver/LvmVg': 'vol',
            'StorDriver/ThinPool': 'thin_pool'
        },
        'provider_kind': 'LVM_THIN',
        'static_traits': {
            'Provisioning': 'Thin',
            'SupportsSnapshots': 'true'
        },
        'storage_pool_name': 'DfltStorPool',
        'total_capacity': 104857600,
        'uuid': '004faf29-be1a-4d74-9470-038bcee2c611'
    },
    {
        'free_capacity': 9223372036854775807,
        'free_space_mgr_name': 'node-1:DfltStorPool',
        'node_name': 'node-1',
        'provider_kind': 'DISKLESS',
        'static_traits': {'SupportsSnapshots': 'false'},
        'storage_pool_name': 'DfltStorPool',
        'total_capacity': 9223372036854775807,
        'uuid': '897da09e-1316-45c0-a308-c07008af42df'
    }
]

STORAGE_POOL_LIST_RESP = [
    {
        'driver_name': 'LVM_THIN',
        'node_name': 'node-2',
        'sp_uuid': '004faf29-be1a-4d74-9470-038bcee2c611',
        'sp_cap': 100.0,
        'sp_free': 100,
        'sp_name': u'DfltStorPool'
    },
    {
        'driver_name': 'DISKLESS',
        'node_name': 'node-1',
        'sp_uuid': '897da09e-1316-45c0-a308-c07008af42df',
        'sp_allocated': 0.0,
        'sp_cap': -1.0,
        'sp_free': -1.0,
        'sp_name': 'DfltStorPool'
    }
]

VOLUME_STATS_RESP = {
    'driver_version': '0.0.7',
    'pools': [{
        'QoS_support': False,
        'backend_state': 'up',
        'filter_function': None,
        'free_capacity_gb': 100,
        'goodness_function': None,
        'location_info': 'linstor://localhost',
        'max_over_subscription_ratio': 0,
        'multiattach': False,
        'pool_name': 'lin-test-driver',
        'provisioned_capacity_gb': 0.0,
        'reserved_percentage': 0,
        'thick_provisioning_support': False,
        'thin_provisioning_support': True,
        'total_capacity_gb': 100.0,
        'total_volumes': 1,
    }],
    'vendor_name': 'LINBIT',
    'volume_backend_name': 'lin-test-driver'
}

CINDER_VOLUME = {
    'id': '0348a7d3-3bb9-452d-9f40-2cf5ebfe9131',
    'name': 'test-lin-vol',
    'size': 1,
    'volume_type_id': 'linstor',
    'created_at': timeutils.utcnow()
}

SNAPSHOT = {
    'id': '0348a7d3-3bb9-452d-9f40-2cf5ebfe9131',
    'volume_id': '0348a7d3-3bb9-452d-9f40-2cf5ebfe9131',
    'volume_size': 1
}

VOLUME_NAMES = {
    'linstor': 'CV_0348a7d3-3bb9-452d-9f40-2cf5ebfe9131',
    'cinder': '0348a7d3-3bb9-452d-9f40-2cf5ebfe9131',
    'snap': 'SN_0348a7d3-3bb9-452d-9f40-2cf5ebfe9131',
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

    def fake_api_resource_dfn_list(self):
        return RESOURCE_DFN_LIST

    def fake_api_snapshot_list(self):
        return SNAPSHOT_LIST_RESP


class LinstorFakeResource(object):

    def __init__(self):
        self.volumes = [{'size': 1069547520}]
        self.id = 0

    def delete(self):
        return True

    def is_diskless(self, host):
        if host in DISKLESS_LIST_RESP:
            return True
        else:
            return False


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
        self.driver.default_pool = STORAGE_POOL_DEF_RESP[0]
        self.driver.host_name = 'node-1'
        self.driver.diskless = True
        self.driver.default_uri = 'linstor://localhost'
        self.driver.default_backend_name = 'lin-test-driver'
        self.driver.configuration.reserved_percentage = 0
        self.driver.configuration.max_over_subscription_ratio = 0
        self.driver.ap_count = 0

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

    @mock.patch('uuid.uuid4')
    def test_clean_uuid_with_braces(self, m_uuid):
        m_uuid.return_value = u'{bd6472d1-dc3c-4d41-a5f0-f44271c05680}'

        val = self.driver._clean_uuid()
        expected = u'bd6472d1-dc3c-4d41-a5f0-f44271c05680'

        m_uuid.assert_called_once()
        self.assertEqual(expected, val)

    # Test volume size conversions
    def test_unit_conversions_to_linstor_1GiB(self):
        val = self.driver._vol_size_to_linstor(1)
        expected = 1044480   # 1048575 - 4096
        self.assertEqual(expected, val)

    def test_unit_conversions_to_linstor_2GiB(self):
        val = self.driver._vol_size_to_linstor(2)
        expected = 2093056   # 2097152 - 4096
        self.assertEqual(expected, val)

    def test_unit_conversions_to_cinder(self):
        val = self.driver._vol_size_to_cinder(1048576)
        expected = 1
        self.assertEqual(expected, val)

    def test_unit_conversions_to_cinder_2GiB(self):
        val = self.driver._vol_size_to_cinder(2097152)
        expected = 2
        self.assertEqual(expected, val)

    def test_is_clean_volume_name(self):
        val = self.driver._is_clean_volume_name(VOLUME_NAMES['cinder'],
                                                drv.DM_VN_PREFIX)
        expected = VOLUME_NAMES['linstor']
        self.assertEqual(expected, val)

    def test_is_clean_volume_name_invalid(self):
        wrong_uuid = 'bc3015e6-695f-4688-91f2-invaliduuid1'
        val = self.driver._is_clean_volume_name(wrong_uuid,
                                                drv.DM_VN_PREFIX)
        expected = None
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
        expected = '/dev/drbd1005'

        m_rsc_list.assert_called_once()
        self.assertEqual(expected, val)

    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_resource_list')
    def test_get_local_path(self, m_rsc_list):
        m_rsc_list.return_value = self._fake_driver.fake_api_resource_list()

        val = self.driver._get_local_path(CINDER_VOLUME)
        expected = '/dev/drbd1005'

        m_rsc_list.assert_called_once()
        self.assertEqual(expected, val)

    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_storage_pool_dfn_list')
    def test_get_spd(self, m_spd_list):
        m_spd_list.return_value = (
            self._fake_driver.fake_api_storage_pool_dfn_list())

        val = self.driver._get_spd()
        expected = STORAGE_POOL_DEF_RESP

        m_spd_list.assert_called_once()
        self.assertEqual(expected, val)

    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_storage_pool_list')
    def test_get_storage_pool(self, m_sp_list):
        m_sp_list.return_value = (
            self._fake_driver.fake_api_storage_pool_list())

        val = self.driver._get_storage_pool()
        expected = STORAGE_POOL_LIST_RESP

        m_sp_list.assert_called_once()
        self.assertEqual(expected, val)

    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_resource_dfn_list')
    def test_get_resource_definitions(self, m_rscd_list):
        m_rscd_list.return_value = (
            self._fake_driver.fake_api_resource_dfn_list())

        val = self.driver._get_resource_definitions()
        expected = RESOURCE_DFN_LIST_RESP

        m_rscd_list.assert_called_once()
        self.assertEqual(expected, val)

    @mock.patch(DRIVER + 'LinstorBaseDriver._get_snapshot_nodes')
    def test_get_snapshot_nodes(self, m_rsc_list):
        m_rsc_list.return_value = self._fake_driver.fake_api_snapshot_list()

        val = self.driver._get_snapshot_nodes(VOLUME_NAMES['linstor'])
        expected = SNAPSHOT_LIST_RESP

        m_rsc_list.assert_called_once()
        self.assertEqual(expected, val)

    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_resource_list')
    def test_get_diskless_nodes(self, m_rsc_list):
        m_rsc_list.return_value = self._fake_driver.fake_api_resource_list()

        val = self.driver._get_diskless_nodes(RESOURCE['name'])
        expected = DISKLESS_LIST_RESP

        m_rsc_list.assert_called_once()
        self.assertEqual(expected, val)

    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_node_list')
    def test_get_linstor_nodes(self, m_node_list):
        m_node_list.return_value = self._fake_driver.fake_api_node_list()

        val = self.driver._get_linstor_nodes()
        expected = RESOURCE_LIST_RESP

        m_node_list.assert_called_once()
        self.assertEqual(expected, val)

    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_node_list')
    def test_get_nodes(self, m_node_list):
        m_node_list.return_value = self._fake_driver.fake_api_node_list()

        val = self.driver._get_nodes()
        expected = NODES_RESP

        m_node_list.assert_called_once()
        self.assertEqual(expected, val)

    @mock.patch(DRIVER + 'LinstorBaseDriver._api_rsc_size')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_rsc_is_diskless')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_resource_list')
    @mock.patch(DRIVER + 'LinstorBaseDriver.get_goodness_function')
    @mock.patch(DRIVER + 'LinstorBaseDriver.get_filter_function')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_resource_dfn_list')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_storage_pool_list')
    def test_get_volume_stats(self,
                              m_sp_list,
                              m_rscd_list,
                              m_filter,
                              m_goodness,
                              m_rsc_list,
                              m_diskless,
                              m_rsc_size):
        m_sp_list.return_value = (
            self._fake_driver.fake_api_storage_pool_list())
        m_rscd_list.return_value = (
            self._fake_driver.fake_api_resource_dfn_list())
        m_filter.return_value = None
        m_goodness.return_value = None
        m_rsc_list.return_value = RESOURCE_LIST
        m_diskless.return_value = True
        m_rsc_size.return_value = 1069547520

        val = self.driver._get_volume_stats()
        expected = VOLUME_STATS_RESP

        m_sp_list.assert_called_once()
        m_rscd_list.assert_called_once()
        self.assertEqual(expected, val)

    @mock.patch(DRIVER + 'LinstorBaseDriver._api_snapshot_create')
    def test_create_snapshot_fail(self,
                                  m_snap_create):
        m_snap_create.return_value = False

        self.assertRaises(cinder_exception.VolumeBackendAPIException,
                          self.driver.create_snapshot, SNAPSHOT)

    @mock.patch(DRIVER + 'LinstorBaseDriver._api_snapshot_create')
    def test_create_snapshot_success(self,
                                     m_snap_create):
        m_snap_create.return_value = True

        # No exception should be raised
        self.assertIsNone(self.driver.create_snapshot(SNAPSHOT))

    @mock.patch(DRIVER + 'LinstorBaseDriver._api_snapshot_delete')
    def test_delete_snapshot_fail(self,
                                  m_snap_delete):
        m_snap_delete.return_value = False

        self.assertRaises(cinder_exception.VolumeBackendAPIException,
                          self.driver.delete_snapshot, SNAPSHOT)

    @mock.patch(DRIVER + 'LinstorBaseDriver._get_snapshot_nodes')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_snapshot_delete')
    def test_delete_snapshot_success(self,
                                     m_snap_delete,
                                     m_snap_nodes):
        m_snap_delete.return_value = True
        m_snap_nodes.return_value = self._fake_driver.fake_api_snapshot_list()

        # No exception should be raised
        self.driver.delete_snapshot(SNAPSHOT)

    @mock.patch(DRIVER + 'LinstorBaseDriver._api_rsc_dfn_delete')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_snapshot_nodes')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_snapshot_delete')
    def test_delete_snapshot_success_cleanup_rd(self,
                                                m_snap_delete,
                                                m_snap_nodes,
                                                m_rd_delete):
        m_snap_delete.return_value = True
        m_snap_nodes.return_value = []
        m_rd_delete.return_value = None

        # No exception should be raised
        self.driver.delete_snapshot(SNAPSHOT)

        # Resource Definition Delete should run once
        m_rd_delete.assert_called_once()

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
        m_lin_nodes.return_value = m_nodes
        m_snap_rsc_restore.return_value = True
        m_rsc_create.return_value = True
        m_vol_extend.return_value = True
        m_vol_dfn.return_value = True
        m_sp_list.return_value = (
            self._fake_driver.fake_api_storage_pool_list())

        # No exception should be raised
        self.assertIsNone(self.driver.create_volume_from_snapshot(
            CINDER_VOLUME, SNAPSHOT))

    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_storage_pool_list')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_volume_dfn_set_sp')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_volume_extend')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_rsc_create')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_snapshot_resource_restore')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_linstor_nodes')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_snapshot_volume_dfn_restore')
    @mock.patch(DRIVER + 'LinstorBaseDriver._check_api_reply')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_rsc_dfn_create')
    def test_create_volume_from_snapshot_fail_restore(self,
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
        m_lin_nodes.return_value = m_nodes
        m_snap_rsc_restore.return_value = False
        m_rsc_create.return_value = True
        m_vol_extend.return_value = True
        m_vol_dfn.return_value = True
        m_sp_list.return_value = (
            self._fake_driver.fake_api_storage_pool_list())

        # Failing to restore a snapshot should raise an exception
        self.assertRaises(cinder_exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          CINDER_VOLUME, SNAPSHOT)

    @mock.patch(DRIVER + 'LinstorBaseDriver.delete_volume')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_storage_pool_list')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_volume_dfn_set_sp')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_volume_extend')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_rsc_create')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_snapshot_resource_restore')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_linstor_nodes')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_snapshot_volume_dfn_restore')
    @mock.patch(DRIVER + 'LinstorBaseDriver._check_api_reply')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_rsc_dfn_create')
    def test_create_volume_from_snapshot_fail_extend(self,
                                                     m_rsc_dfn_create,
                                                     m_api_reply,
                                                     m_snap_vd_restore,
                                                     m_lin_nodes,
                                                     m_snap_rsc_restore,
                                                     m_rsc_create,
                                                     m_vol_extend,
                                                     m_vol_dfn,
                                                     m_sp_list,
                                                     m_delete_volume):
        m_rsc_dfn_create.return_value = True
        m_api_reply.return_value = False
        m_snap_vd_restore.return_value = True
        m_nodes = []
        m_lin_nodes.return_value = m_nodes
        m_snap_rsc_restore.return_value = True
        m_rsc_create.return_value = True
        m_vol_extend.return_value = True
        m_vol_dfn.return_value = True
        m_sp_list.return_value = (
            self._fake_driver.fake_api_storage_pool_list())
        m_delete_volume.return_value = True

        # Failing to extend the volume after a snapshot restoration should
        # raise an exception
        new_volume = CINDER_VOLUME
        new_volume['size'] = 2
        self.assertRaises(cinder_exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          new_volume, SNAPSHOT)

    @mock.patch(DRIVER + 'LinstorBaseDriver._check_api_reply')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_rsc_create')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_volume_dfn_create')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_rsc_dfn_create')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_storage_pool_create')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_storage_pool_dfn_list')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_node_list')
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
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_node_list')
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
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_node_list')
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
        self.assertEqual(expected, val)

    @mock.patch(DRIVER + 'LinstorBaseDriver._api_rsc_auto_delete')
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
                                           m_api_reply,
                                           m_rsc_auto_delete):
        m_rsc_list.return_value = self._fake_driver.fake_api_resource_list()
        m_rsc_delete.return_value = True
        m_vol_dfn_delete.return_value = True
        m_rsc_dfn_delete.return_value = True
        m_api_reply.return_value = False
        m_rsc_auto_delete.return_value = True

        test_volume = CINDER_VOLUME
        test_volume['display_name'] = 'linstor_test'
        test_volume['host'] = 'node_one'
        test_volume['size'] = 1

        self.assertRaises(cinder_exception.VolumeBackendAPIException,
                          self.driver.delete_volume, test_volume)

    @mock.patch(DRIVER + 'LinstorBaseDriver._api_rsc_auto_delete')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_diskless_nodes')
    @mock.patch(DRIVER + 'LinstorBaseDriver._check_api_reply')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_rsc_dfn_delete')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_volume_dfn_delete')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_rsc_delete')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_resource_list')
    def test_delete_volume_fail_diskless_remove(self,
                                                m_rsc_list,
                                                m_rsc_delete,
                                                m_vol_dfn_delete,
                                                m_rsc_dfn_delete,
                                                m_api_reply,
                                                m_diskless,
                                                m_rsc_auto_delete):
        m_rsc_list.return_value = self._fake_driver.fake_api_resource_list()
        m_rsc_delete.return_value = False
        m_vol_dfn_delete.return_value = True
        m_rsc_dfn_delete.return_value = True
        m_api_reply.return_value = False
        m_diskless.return_value = ['foo']
        m_rsc_auto_delete.return_value = True

        test_volume = CINDER_VOLUME
        test_volume['display_name'] = 'linstor_test'
        test_volume['host'] = 'node_one'
        test_volume['size'] = 1

        # Raises exception for failing to delete a diskless resource
        self.assertRaises(cinder_exception.VolumeBackendAPIException,
                          self.driver.delete_volume, test_volume)

    @mock.patch(DRIVER + 'LinstorBaseDriver._api_rsc_auto_delete')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_snapshot_nodes')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_diskless_nodes')
    @mock.patch(DRIVER + 'LinstorBaseDriver._check_api_reply')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_rsc_dfn_delete')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_volume_dfn_delete')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_rsc_delete')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_resource_list')
    def test_delete_volume_fail_diskful_remove(self,
                                               m_rsc_list,
                                               m_rsc_delete,
                                               m_vol_dfn_delete,
                                               m_rsc_dfn_delete,
                                               m_api_reply,
                                               m_diskless,
                                               m_snap_nodes,
                                               m_rsc_auto_delete):
        m_rsc_list.return_value = self._fake_driver.fake_api_resource_list()
        m_rsc_delete.return_value = False
        m_vol_dfn_delete.return_value = True
        m_rsc_dfn_delete.return_value = True
        m_api_reply.return_value = False
        m_diskless.return_value = []
        m_snap_nodes.return_value = ['foo']
        m_rsc_auto_delete.return_value = True

        test_volume = CINDER_VOLUME
        test_volume['display_name'] = 'linstor_test'
        test_volume['host'] = 'node_one'
        test_volume['size'] = 1

        # Raises exception for failing to delete a diskful resource
        self.assertRaises(cinder_exception.VolumeBackendAPIException,
                          self.driver.delete_volume, test_volume)

    @mock.patch(DRIVER + 'LinstorBaseDriver._api_rsc_auto_delete')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_snapshot_nodes')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_diskless_nodes')
    @mock.patch(DRIVER + 'LinstorBaseDriver._check_api_reply')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_rsc_dfn_delete')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_volume_dfn_delete')
    @mock.patch(DRIVER + 'LinstorBaseDriver._api_rsc_delete')
    @mock.patch(DRIVER + 'LinstorBaseDriver._get_api_resource_list')
    def test_delete_volume_fail_volume_definition(self,
                                                  m_rsc_list,
                                                  m_rsc_delete,
                                                  m_vol_dfn_delete,
                                                  m_rsc_dfn_delete,
                                                  m_api_reply,
                                                  m_diskless,
                                                  m_snap_nodes,
                                                  m_rsc_auto_delete):
        m_rsc_list.return_value = self._fake_driver.fake_api_resource_list()
        m_rsc_delete.return_value = True
        m_vol_dfn_delete.return_value = False
        m_rsc_dfn_delete.return_value = True
        m_api_reply.return_value = False
        m_diskless.return_value = []
        m_snap_nodes.return_value = []
        m_rsc_auto_delete.return_value = True

        test_volume = CINDER_VOLUME
        test_volume['display_name'] = 'linstor_test'
        test_volume['host'] = 'node_one'
        test_volume['size'] = 1

        # Raises exception for failing to delete a volume definition
        self.assertRaises(cinder_exception.VolumeBackendAPIException,
                          self.driver.delete_volume, test_volume)

    @mock.patch(DRIVER + 'LinstorBaseDriver._api_rsc_auto_delete')
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
                           m_api_reply,
                           m_rsc_auto_delete):
        m_rsc_list.return_value = self._fake_driver.fake_api_resource_list()
        m_rsc_delete.return_value = True
        m_vol_dfn_delete.return_value = True
        m_rsc_dfn_delete.return_value = True
        m_api_reply.return_value = True
        m_rsc_auto_delete.return_value = True

        test_volume = CINDER_VOLUME
        test_volume['display_name'] = 'linstor_test'
        test_volume['host'] = 'node_one'
        test_volume['size'] = 1

        val = self.driver.delete_volume(test_volume)
        expected = True
        self.assertEqual(expected, val)

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
        self.assertEqual(expected, val)


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
        self.driver.default_pool = STORAGE_POOL_DEF_RESP[0]
        self.driver.host_name = 'node_one'
        self.driver.diskless = True
        self.driver.location_info = 'LinstorIscsi:linstor://localhost'
        self.driver.default_backend_name = 'lin-test-driver'
        self.driver.configuration.reserved_percentage = int('0')
        self.driver.configuration.max_over_subscription_ratio = int('0')

    @mock.patch(DRIVER + 'LinstorIscsiDriver._get_api_resource_list')
    @mock.patch(DRIVER + 'LinstorIscsiDriver._get_volume_stats')
    def test_iscsi_get_volume_stats(self, m_vol_stats, m_rsc_list):

        m_vol_stats.return_value = VOLUME_STATS_RESP
        m_rsc_list.return_value = RESOURCE_LIST

        val = self.driver.get_volume_stats()

        expected = VOLUME_STATS_RESP
        expected["storage_protocol"] = 'iSCSI'
        self.assertEqual(expected, val)

    @mock.patch(DRIVER + 'linstor')
    def test_iscsi_check_for_setup_error_pass(self, m_linstor):
        m_linstor.return_value = True

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
        self.driver.default_pool = STORAGE_POOL_DEF_RESP[0]
        self.driver.host_name = 'node_one'
        self.driver.diskless = True
        self.driver.location_info = 'LinstorDrbd:linstor://localhost'
        self.driver.default_backend_name = 'lin-test-driver'
        self.driver.configuration.reserved_percentage = int('0')
        self.driver.configuration.max_over_subscription_ratio = int('0')

    @mock.patch(DRIVER + 'LinstorDrbdDriver._get_rsc_path')
    def test_drbd_return_drbd_config(self, m_rsc_path):
        m_rsc_path.return_value = '/dev/drbd1005'

        val = self.driver._return_drbd_config(CINDER_VOLUME)

        expected = {
            'driver_volume_type': 'local',
            'data': {
                "device_path": str(m_rsc_path.return_value)
            }
        }
        self.assertEqual(expected, val)

    @mock.patch(DRIVER + 'LinstorDrbdDriver._get_api_storage_pool_list')
    def test_drbd_node_in_sp(self, m_sp_list):
        m_sp_list.return_value = (
            self._fake_driver.fake_api_storage_pool_list())

        val = self.driver._node_in_sp('node-1')
        self.assertTrue(val)

    @mock.patch(DRIVER + 'LinstorDrbdDriver._get_volume_stats')
    def test_drbd_get_volume_stats(self, m_vol_stats):
        m_vol_stats.return_value = VOLUME_STATS_RESP

        val = self.driver.get_volume_stats()
        expected = VOLUME_STATS_RESP
        expected["storage_protocol"] = 'DRBD'
        self.assertEqual(expected, val)

    @mock.patch(DRIVER + 'linstor')
    def test_drbd_check_for_setup_error_pass(self, m_linstor):
        m_linstor.return_value = True

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
        self.assertEqual(expected, val)

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
