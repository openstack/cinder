# Copyright (c) 2019 SandStone data Technologies Co., Ltd
# All Rights Reserved
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
"""Unittest for sds_client."""
from unittest import mock
import uuid

import ddt
from oslo_utils import units

from cinder import exception
from cinder import objects
from cinder.tests.unit import test
from cinder.volume import configuration as config
from cinder.volume.drivers.san import san
from cinder.volume.drivers.sandstone import sds_client
from cinder.volume.drivers.sandstone import sds_driver


class FakeSdsBaseDriver(sds_driver.SdsBaseDriver):
    """Fake sds base driver."""

    def __init__(self):
        """Init conf client pool sds_client."""
        self.configuration = config.Configuration(None)
        self.configuration.append_config_values(sds_driver.sds_opts)
        self.configuration.append_config_values(san.san_opts)
        self.configuration.suppress_requests_ssl_warnings = True
        self.client = None
        self.poolid = 1
        self.VERSION = '1.0'
        self.address = "192.168.200.100"
        self.user = "fake_user"
        self.password = "fake_password"
        self.pool = "fake_pool_name"
        self.iscsi_info = {"iqn.1994-05.com.redhat:899c5f9d15d":
                           "1.1.1.1,1.1.1.2,1.1.1.3"}
        self.default_target_ips = ["1.1.1.1", "1.1.1.2", "1.1.1.3"]
        self.default_chap_info = "1234567891234,123456789123"


@ddt.ddt
class TestSdsBaseDriver(test.TestCase):
    """Testcase sds base driver."""

    def setUp(self):
        """Setup."""
        super(TestSdsBaseDriver, self).setUp()
        self.fake_driver = FakeSdsBaseDriver()
        self.fake_driver.client = sds_client.RestCmd('192.168.200.100',
                                                     'fake_user',
                                                     'fake_password',
                                                     True)

    # @mock.patch.object(sds_client.RestCmd, 'login')
    def test_do_setup(self):
        """Do setup."""
        self.fake_driver.client = sds_client.RestCmd(
            'fake_rest_ip', 'user', 'password', True)
        self.fake_driver.configuration.san_ip = 'fake_rest_ip'
        self.fake_driver.configuration.san_login = 'fake_san_user'
        self.fake_driver.configuration.san_password = 'fake_san_password'
        self.fake_driver.do_setup('context')

    @mock.patch.object(sds_client.RestCmd, 'query_pool_info')
    @mock.patch.object(sds_client.RestCmd, 'get_poolid_from_poolname')
    @mock.patch.object(sds_client.RestCmd, 'login')
    def test_check_for_setup_error(self, mock_login,
                                   mock_get_poolid_from_poolname,
                                   mock_query_pool_info):
        """Test pool status health or not."""
        result1 = [
            {'status': {'progress': 33, 'state': ['degraded'], 'flags': 4},
             'pool_name': 'fake_pool_name', 'used': 1792950890,
             'display_name': 'data', 'replicated_size': 2,
             'storage_policy': '2', 'domain_name': 'sandstone',
             'pool_id': 3, 'min_size': 1, 'erasure_code_profile': '',
             'policy_type': 'replicated', 'rule_id': 1,
             'size': 2},
            {'status': {'progress': 33, 'state': ['degraded'], 'flags': 4},
             'pool_name': 'vms1', 'used': 1792950890,
             'display_name': 'data', 'replicated_size': 2,
             'storage_policy': '2', 'domain_name': 'sandstone',
             'pool_id': 3, 'min_size': 1, 'erasure_code_profile': '',
             'policy_type': 'replicated', 'rule_id': 1,
             'size': 2}]
        result2 = [
            {'status': {'progress': 33, 'state': ['degraded'], 'flags': 4},
             'pool_name': 'vms', 'used': 1792950890,
             'display_name': 'data', 'replicated_size': 2,
             'storage_policy': '2', 'domain_name': 'sandstone',
             'pool_id': 3, 'min_size': 1, 'erasure_code_profile': '',
             'policy_type': 'replicated', 'rule_id': 1,
             'size': 2},
            {'status': {'progress': 33, 'state': ['degraded'], 'flags': 4},
             'pool_name': 'vms1', 'used': 1792950890,
             'display_name': 'data', 'replicated_size': 2,
             'storage_policy': '2', 'domain_name': 'sandstone',
             'pool_id': 3, 'min_size': 1, 'erasure_code_profile': '',
             'policy_type': 'replicated', 'rule_id': 1,
             'size': 2}]

        mock_login.return_value = {"success": 1}
        mock_get_poolid_from_poolname.return_value = (
            {"fake_pool_name": 3})
        mock_query_pool_info.return_value = result1
        retval = self.fake_driver.check_for_setup_error()
        self.assertIsNone(retval)
        mock_query_pool_info.return_value = result2
        try:
            self.fake_driver.check_for_setup_error()
        except Exception as e:
            self.assertEqual(exception.InvalidInput, type(e))

    @mock.patch.object(sds_client.RestCmd, 'query_capacity_info')
    def test__update_volume_stats(self, mock_query_capacity_info):
        """Get cluster capacity."""
        result1 = {
            "capacity_bytes": 2 * units.Gi,
            "free_bytes": units.Gi
        }
        mock_query_capacity_info.return_value = result1
        retval = self.fake_driver._update_volume_stats(
            pool_name="fake_pool_name")
        self.assertDictEqual(
            {"pools": [dict(
                pool_name="fake_pool_name",
                vendor_name = 'SandStone USP',
                driver_version = self.fake_driver.VERSION,
                total_capacity_gb=2.0,
                free_capacity_gb=1.0,
                QoS_support=True,
                thin_provisioning_support=True,
                multiattach=False,)
            ]}, retval)
        mock_query_capacity_info.assert_called_once_with()

    @mock.patch.object(sds_driver.SdsBaseDriver, 'get_volume_stats')
    def test_get_volume_stats(self, mock_get_volume_stats):
        """Get cluster capacitys."""
        result1 = {"pool": dict(
            pool_name="fake_pool_name",
            total_capacity_gb=2.0,
            free_capacity_gb=1.0,
            QoS_support=True,
            thin_provisioning_support=True,
            multiattach=False,)}
        mock_get_volume_stats.return_value = result1
        retval = self.fake_driver.get_volume_stats()
        self.assertDictEqual(
            {"pool": dict(
                pool_name="fake_pool_name",
                total_capacity_gb=2.0,
                free_capacity_gb=1.0,
                QoS_support=True,
                thin_provisioning_support=True,
                multiattach=False,
            )}, retval)

    @mock.patch.object(sds_client.RestCmd, 'create_lun')
    def test_create_volume(self, mock_create_lun):
        """Test create volume."""
        volume = objects.Volume(_name_id=uuid.uuid4(), size=1)
        mock_create_lun.return_value = {'success': 1}
        retval = self.fake_driver.create_volume(volume=volume)
        self.assertIsNone(retval)

    @mock.patch.object(sds_client.RestCmd, 'delete_lun')
    def test_delete_volume(self, mock_delete_):
        """Test delete volume."""
        mock_delete_.return_value = {'success': 1}
        volume = objects.Volume(_name_id=uuid.uuid4(), size=1)
        retval = self.fake_driver.delete_volume(volume)
        self.assertIsNone(retval)

    @mock.patch.object(sds_client.RestCmd, 'extend_lun')
    @mock.patch.object(sds_client.RestCmd, 'create_lun_from_snapshot')
    def test_create_volume_from_snapshot(self, mock_lun_from_snapshot,
                                         mock_extend_lun):
        """Test create new volume from snapshot of src volume."""
        volume = objects.Volume(_name_id=uuid.uuid4(), size=1)
        snapshot = objects.Snapshot(
            id=uuid.uuid4(), volume_size=2, volume=volume)
        mock_lun_from_snapshot.return_value = {'success': 1}
        mock_extend_lun.return_value = {'success': 1}
        retval = self.fake_driver.create_volume_from_snapshot(volume, snapshot)
        self.assertIsNone(retval)

    @mock.patch.object(sds_client.RestCmd, 'extend_lun')
    @mock.patch.object(sds_client.RestCmd, 'create_lun_from_lun')
    @mock.patch.object(sds_driver.SdsBaseDriver, '_check_volume_exist')
    def test_create_cloned_volume(self, mock__check_volume_exist,
                                  mock_create_lun_from_lun,
                                  mock_extend_lun):
        """Test create clone volume."""
        mock__check_volume_exist.return_value = True
        mock_create_lun_from_lun.return_value = {'success': 1}
        mock_extend_lun.return_value = {'success': 1}
        dst_volume = objects.Volume(_name_id=uuid.uuid4(), size=2)
        src_volume = objects.Volume(_name_id=uuid.uuid4(), size=1)
        retval = self.fake_driver.create_cloned_volume(dst_volume, src_volume)
        self.assertIsNone(retval)

    @mock.patch.object(sds_client.RestCmd, 'query_lun_by_name')
    def test__check_volume_exist(self, mock_query_lun_by_name):
        """Test volume exist or not."""
        mock_query_lun_by_name.return_value = {'success': 1}
        volume = objects.Volume(_name_id=uuid.uuid4(), size=1)
        retval = self.fake_driver._check_volume_exist(volume)
        self.assertEqual({'success': 1}, retval)

    @mock.patch.object(sds_client.RestCmd, 'extend_lun')
    @mock.patch.object(sds_driver.SdsBaseDriver, '_check_volume_exist')
    def test_extend_volume(self, mock__check_volume_exist, mock_extend_lun):
        """Test resize volume."""
        volume = objects.Volume(_name_id=uuid.uuid4(), size=1)
        new_size = 3
        mock__check_volume_exist.return_value = {
            'capacity_bytes': units.Gi * 1}
        mock_extend_lun.return_value = {'success': 1}
        retval = self.fake_driver.extend_volume(volume, new_size)
        self.assertIsNone(retval)

    @mock.patch.object(sds_client.RestCmd, 'create_snapshot')
    def test_create_snapshot(self, mock_create_snapshot):
        """Test create snapshot of volume."""
        volume = objects.Volume(_name_id=uuid.uuid4(), size=1)
        snapshot = objects.Snapshot(
            id=uuid.uuid4(), volume_size=2, volume=volume)
        mock_create_snapshot.return_value = {'success': 1}
        retval = self.fake_driver.create_snapshot(snapshot)
        self.assertIsNone(retval)

    @mock.patch.object(sds_client.RestCmd, 'query_snapshot_by_name')
    def test__check_snapshot_exist(self, mock_query_snapshot_by_name):
        """Test snapshot exist or not."""
        volume = objects.Volume(_name_id=uuid.uuid4(), size=1)
        snapshot = objects.Snapshot(
            id=uuid.uuid4(), volume_size=2, volume=volume)
        mock_query_snapshot_by_name.return_value = {'success': 1}
        retval = self.fake_driver._check_snapshot_exist(snapshot)
        self.assertEqual({'success': 1}, retval)

    @mock.patch.object(sds_client.RestCmd, 'delete_snapshot')
    @mock.patch.object(sds_driver.SdsBaseDriver, '_check_snapshot_exist')
    def test_delete_snapshot(self, mock__check_snapshot_exist,
                             mock_delete_snapshot):
        """Test delete snapshot."""
        volume = objects.Volume(_name_id=uuid.uuid4(), size=1)
        snapshot = objects.Snapshot(
            id=uuid.uuid4(), volume_size=2, volume=volume)
        mock__check_snapshot_exist.return_value = True
        mock_delete_snapshot.return_value = {'success': 1}
        retval = self.fake_driver.delete_snapshot(snapshot)
        self.assertIsNone(retval)


class FakeSdsISCSIDriver(sds_driver.SdsISCSIDriver):
    """Fake sds iscsi driver, include attach, detach."""

    def __init__(self):
        """Init conf client pool."""
        self.configuration = config.Configuration(None)
        self.client = None
        self.address = "192.168.200.100"
        self.user = "fake_user"
        self.password = "fake_password"
        self.pool = "fake_pool_name"
        self.poolid = 1
        self.iscsi_info = {"iqn.1994-05.com.redhat:899c5f9d15d":
                           "1.1.1.1,1.1.1.2,1.1.1.3"}
        self.default_target_ips = ["1.1.1.1", "1.1.1.2", "1.1.1.3"]
        self.chap_username = "123456789123"
        self.chap_password = "1234567891234"


@ddt.ddt
class TestSdsISCSIDriver(test.TestCase):
    """Testcase sds iscsi driver, include attach, detach."""

    def setUp(self):
        """Setup."""
        super(TestSdsISCSIDriver, self).setUp()
        self.fake_driver = FakeSdsISCSIDriver()
        self.fake_driver.client = sds_client.RestCmd("192.168.200.100",
                                                     "fake_user",
                                                     "fake_password",
                                                     True)

    @mock.patch.object(sds_client.RestCmd, 'query_target_by_name')
    def test__check_target_exist(self, mock_query_target_by_name):
        """Test target exist or not."""
        target_name = 'test_driver'
        mock_query_target_by_name.return_value = {'success': 1}
        retval = self.fake_driver._check_target_exist(target_name)
        self.assertEqual({'success': 1}, retval)

    @mock.patch.object(sds_client.RestCmd, 'query_initiator_by_name')
    def test__check_initiator_exist(self, mock_query_initiator_by_name):
        """Test initiator exist or not."""
        initiator_name = 'test_driver'
        mock_query_initiator_by_name.return_value = {'success': 1}
        retval = self.fake_driver._check_initiator_exist(initiator_name)
        self.assertEqual({'success': 1}, retval)

    @mock.patch.object(sds_client.RestCmd, 'query_target_initiatoracl')
    def test__check_target_added_initiator(self,
                                           mock_query_target_initiatoracl):
        """Test target added the initiator."""
        mock_query_target_initiatoracl.return_value = {'success': 1}
        target_name, initiator_name = 'test_driver', 'initiator_name'
        retval = self.fake_driver._check_target_added_initiator(target_name,
                                                                initiator_name)
        self.assertEqual({'success': 1}, retval)

    @mock.patch.object(sds_client.RestCmd, 'query_target_lunacl')
    def test__check_target_added_lun(self, mock_query_target_lunacl):
        """Test target added the lun."""
        mock_query_target_lunacl.return_value = {'success': 1}
        target_name, pool_name, volume_name = ('ccc', self.fake_driver.pool,
                                               'fcc')
        retval = self.fake_driver._check_target_added_lun(target_name,
                                                          pool_name,
                                                          volume_name)
        self.assertEqual({'success': 1}, retval)

    @mock.patch.object(sds_client.RestCmd, 'query_chapinfo_by_target')
    def test__check_target_added_chap(self, mock_query_chapinfo_by_target):
        """Test target added chapuser."""
        mock_query_chapinfo_by_target.return_value = {'success': 1}
        target_name, user_name = 'ccc', 'fcc'
        retval = self.fake_driver._check_target_added_chap(target_name,
                                                           user_name)
        self.assertEqual({'success': 1}, retval)

    def test__get_target_ip(self):
        """Test get target from targetip."""
        initiator = 'iqn.1994-05.com.redhat:899c5f9d15d'
        retval_target_ips = \
            self.fake_driver._get_target_ip(initiator)
        self.assertListEqual(['1.1.1.1', '1.1.1.2', '1.1.1.3'],
                             retval_target_ips)

        self.fake_driver.default_target_ips = \
            ["1.1.1.1"]
        initiator = 'vms'
        retval_target_ips = \
            self.fake_driver._get_target_ip(initiator)
        self.assertListEqual(["1.1.1.1"], retval_target_ips)

    @mock.patch.object(sds_client.RestCmd, 'add_chap_by_target')
    @mock.patch.object(sds_driver.SdsISCSIDriver, '_check_target_added_chap')
    @mock.patch.object(sds_driver.SdsISCSIDriver, '_check_target_added_lun')
    @mock.patch.object(sds_client.RestCmd, 'mapping_lun')
    @mock.patch.object(sds_client.RestCmd, 'add_initiator_to_target')
    @mock.patch.object(sds_driver.SdsISCSIDriver,
                       '_check_target_added_initiator')
    @mock.patch.object(sds_client.RestCmd, 'create_initiator')
    @mock.patch.object(sds_driver.SdsISCSIDriver, '_check_initiator_exist')
    @mock.patch.object(sds_client.RestCmd, 'create_target')
    @mock.patch.object(sds_client.RestCmd, 'query_node_by_targetips')
    @mock.patch.object(sds_driver.SdsISCSIDriver, '_check_target_exist')
    @mock.patch.object(sds_driver.SdsISCSIDriver, '_get_target_ip')
    def test_initialize_connection(self, mock__get_target_ip,
                                   mock__check_target_exist,
                                   mock_query_node_by_targetips,
                                   mock_create_target,
                                   mock__check_initiator_exist,
                                   mock_create_initiator,
                                   mock__check_target_added_initiator,
                                   mock_add_initiator_to_target,
                                   mock_mapping_lun,
                                   mock__check_target_added_lun,
                                   mock__check_target_added_chap,
                                   mock_add_chap_by_target):
        """Test attach volume to kvm."""
        mock__get_target_ip.return_value = (['1.1.1.1', '1.1.1.2', '1.1.1.3'])
        mock__check_target_exist.return_value = False
        mock__check_initiator_exist.return_value = False
        mock__check_target_added_initiator.result_value = False
        mock__check_target_added_chap.return_value = False
        mock_query_node_by_targetips.return_value = {'host_id', 'address'}
        mock_create_target.return_value = {'success': 1}
        mock_create_initiator.return_value = {'success': 1}
        mock_add_initiator_to_target.result_value = {'success': 1}
        mock_mapping_lun.return_value = {'success': 1}
        mock__check_target_added_lun.return_value = 1
        mock_add_chap_by_target.return_value = {'success': 1}

        volume1, connector1 = (objects.Volume(id=uuid.uuid4(),
                                              _name_id=uuid.uuid4(), size=1),
                               {'initiator':
                                'iqn.1994-05.com.redhat:899c5f9d15d',
                                'multipath': True})
        initiator_name = connector1['initiator']
        iqn_end = initiator_name.split(':', 1)[1]
        target_head = 'iqn.2014-10.com.szsandstone:storage:'
        target_name = target_head + iqn_end
        result1 = {
            'driver_volume_type': 'iscsi',
            'data': {'target_discovered': True,
                     'target_portals': ['1.1.1.1:3260',
                                        '1.1.1.2:3260',
                                        '1.1.1.3:3260'],
                     'volume_id': volume1.id,
                     'auth_method': 'CHAP',
                     'auth_username': '123456789123',
                     'auth_password': '1234567891234',
                     'target_iqns': [target_name, target_name, target_name],
                     'target_luns': [1, 1, 1]}}
        retval = self.fake_driver.initialize_connection(volume1, connector1)
        self.assertDictEqual(result1, retval)

        volume2, connector2 = (objects.Volume(id=uuid.uuid4(),
                                              _name_id=uuid.uuid4(),
                                              size=2),
                               {'initiator':
                                'iqn.1994-05.com.redhat:899c5f9d15d'})
        mock__get_target_ip.return_value = (['1.1.1.1', '1.1.1.2', '1.1.1.3'])
        initiator_name = connector2['initiator']
        iqn_end = initiator_name.split(':', 1)[1]
        target_head = 'iqn.2014-10.com.szsandstone:storage:'
        target_name = target_head + iqn_end
        result2 = {'driver_volume_type': 'iscsi',
                   'data': {'target_discovered': True,
                            'target_portal': '1.1.1.1:3260',
                            'volume_id': volume2.id,
                            'target_iqn': target_name,
                            'target_lun': 1,
                            'auth_method': 'CHAP',
                            'auth_username': '123456789123',
                            'auth_password': '1234567891234'}}
        retval = self.fake_driver.initialize_connection(volume2, connector2)
        self.assertDictEqual(result2, retval)

    @mock.patch.object(sds_client.RestCmd, 'unmap_lun')
    def test_terminate_connection(self, mock_unmap_lun):
        """Test detach volume from kvm."""
        volume, connector = (objects.Volume(_name_id=uuid.uuid4(), size=1),
                             {'initiator':
                              'iqn.1994-05.com.redhat:899c5f9d15d'})
        mock_unmap_lun.result_value = {'success': 1}
        retval = self.fake_driver.terminate_connection(volume, connector)
        self.assertIsNone(retval)
