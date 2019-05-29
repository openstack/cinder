# Copyright (c) 2016 EMC Corporation.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
import mock
import os
import re

from oslo_config import cfg

from cinder import exception
from cinder.objects import fields
from cinder.tests.unit import fake_constants
from cinder.tests.unit import utils as test_utils
from cinder.tests.unit.volume.drivers.dell_emc.vnx import fake_exception \
    as storops_ex
from cinder.tests.unit.volume.drivers.dell_emc.vnx import fake_storops \
    as storops
from cinder.tests.unit.volume.drivers.dell_emc.vnx import res_mock
from cinder.tests.unit.volume.drivers.dell_emc.vnx import test_base
from cinder.tests.unit.volume.drivers.dell_emc.vnx import utils
from cinder.volume.drivers.dell_emc.vnx import adapter
from cinder.volume.drivers.dell_emc.vnx import client
from cinder.volume.drivers.dell_emc.vnx import common
from cinder.volume.drivers.dell_emc.vnx import utils as vnx_utils


class TestCommonAdapter(test_base.TestCase):

    def setUp(self):
        super(TestCommonAdapter, self).setUp()
        vnx_utils.init_ops(self.configuration)

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_create_volume(self, vnx_common, _ignore, mocked_input):
        volume = mocked_input['volume']
        with mock.patch.object(vnx_utils, 'get_backend_qos_specs',
                               return_value=None):
            model_update = vnx_common.create_volume(volume)
            self.assertEqual('False', model_update.get('metadata')['snapcopy'])

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_create_volume_error(self, vnx_common, _ignore, mocked_input):
        def inner():
            with mock.patch.object(vnx_utils, 'get_backend_qos_specs',
                                   return_value=None):
                vnx_common.create_volume(mocked_input['volume'])
        self.assertRaises(storops_ex.VNXCreateLunError, inner)

    @utils.patch_extra_specs({'provisioning:type': 'thick'})
    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_create_thick_volume(self, vnx_common, _ignore, mocked_input):
        volume = mocked_input['volume']
        expected_pool = volume.host.split('#')[1]
        with mock.patch.object(vnx_utils, 'get_backend_qos_specs',
                               return_value=None):
            vnx_common.create_volume(volume)
        vnx_common.client.vnx.get_pool.assert_called_with(
            name=expected_pool)

    @utils.patch_extra_specs({'provisioning:type': 'thin'})
    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_create_volume_with_qos(self, vnx_common, _ignore, mocked_input):
        volume = mocked_input['volume']
        with mock.patch.object(vnx_utils, 'get_backend_qos_specs',
                               return_value={'id': 'test',
                                             'maxBWS': 100,
                                             'maxIOPS': 123}):
            model_update = vnx_common.create_volume(volume)
        self.assertEqual('False', model_update.get('metadata')['snapcopy'])

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_migrate_volume(self, vnx_common, mocked, cinder_input):
        volume = cinder_input['volume']
        host = {'capabilities':
                {'location_info': 'pool_name|fake_serial',
                 'storage_protocol': 'iscsi'},
                'host': 'hostname@backend_name#pool_name'}
        vnx_common.serial_number = 'fake_serial'
        migrated, update = vnx_common.migrate_volume(None, volume, host)
        self.assertTrue(migrated)
        self.assertEqual('False', update['metadata']['snapcopy'])

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_migrate_volume_host_assisted(self, vnx_common, mocked,
                                          cinder_input):
        volume1 = cinder_input['volume']
        host = {
            'capabilities': {
                'location_info': 'pool_name|fake_serial',
                'storage_protocol': 'iscsi'},
            'host': 'hostname@backend_name#pool_name'}
        vnx_common.serial_number = 'new_serial'
        migrated, update = vnx_common.migrate_volume(None, volume1, host)
        self.assertFalse(migrated)
        self.assertIsNone(update)

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_create_cloned_volume(
            self, vnx_common, mocked, cinder_input):
        volume = cinder_input['volume']
        src_vref = cinder_input['src_vref']
        model_update = vnx_common.create_cloned_volume(volume, src_vref)
        self.assertEqual('False', model_update['metadata']['snapcopy'])

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_create_cloned_volume_snapcopy(
            self, vnx_common, mocked, cinder_input):
        volume = cinder_input['volume']
        volume.metadata = {'snapcopy': 'True'}
        src_vref = cinder_input['src_vref']
        model_update = vnx_common.create_cloned_volume(volume, src_vref)
        self.assertEqual('True', model_update['metadata']['snapcopy'])

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_create_volume_from_snapshot(
            self, vnx_common, mocked, cinder_input):
        volume = cinder_input['volume']
        volume['metadata'] = {'async_migrate': 'False'}
        snapshot = cinder_input['snapshot']
        snapshot.volume = volume
        update = vnx_common.create_volume_from_snapshot(volume, snapshot)
        self.assertEqual('False', update['metadata']['snapcopy'])

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_create_volume_from_snapshot_snapcopy(
            self, vnx_common, mocked, cinder_input):
        volume = cinder_input['volume']
        volume.metadata = {'snapcopy': 'True'}
        snapshot = cinder_input['snapshot']
        snapshot.volume = volume
        update = vnx_common.create_volume_from_snapshot(volume, snapshot)
        self.assertEqual('True', update['metadata']['snapcopy'])

    @res_mock.patch_common_adapter
    def test_create_cg_from_cgsnapshot(self, common, _):
        common.do_create_cg_from_cgsnap = mock.Mock(
            return_value='fake_return')
        new_cg = test_utils.create_consistencygroup(
            self.ctxt,
            id=fake_constants.CONSISTENCY_GROUP_ID,
            host='host@backend#unit_test_pool',
            group_type_id=fake_constants.VOLUME_TYPE_ID)
        cg_snapshot = test_utils.create_cgsnapshot(
            self.ctxt,
            fake_constants.CONSISTENCY_GROUP2_ID)
        vol = test_utils.create_volume(self.ctxt)
        snaps = [
            test_utils.create_snapshot(self.ctxt, vol.id)]
        vol_new = test_utils.create_volume(self.ctxt)
        ret = common.create_cg_from_cgsnapshot(
            None, new_cg, [vol_new], cg_snapshot, snaps)
        self.assertEqual('fake_return', ret)
        common.do_create_cg_from_cgsnap.assert_called_once_with(
            new_cg.id, new_cg.host, [vol_new], cg_snapshot.id, snaps)

    @res_mock.patch_common_adapter
    def test_create_group_from_group_snapshot(self, common, _):
        common.do_create_cg_from_cgsnap = mock.Mock(
            return_value='fake_return')
        group = test_utils.create_group(
            self.ctxt,
            id=fake_constants.CONSISTENCY_GROUP_ID,
            host='host@backend#unit_test_pool',
            group_type_id=fake_constants.VOLUME_TYPE_ID)
        group_snapshot = test_utils.create_group_snapshot(
            self.ctxt,
            fake_constants.CGSNAPSHOT_ID,
            group_type_id=fake_constants.VOLUME_TYPE_ID)
        vol = test_utils.create_volume(self.ctxt)
        snaps = [
            test_utils.create_snapshot(self.ctxt, vol.id)]
        vol_new = test_utils.create_volume(self.ctxt)
        ret = common.create_group_from_group_snapshot(
            None, group, [vol_new], group_snapshot, snaps)
        self.assertEqual('fake_return', ret)
        common.do_create_cg_from_cgsnap.assert_called_once_with(
            group.id, group.host, [vol_new], group_snapshot.id, snaps)

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_do_create_cg_from_cgsnap(
            self, vnx_common, mocked, cinder_input):
        cg_id = fake_constants.CONSISTENCY_GROUP_ID
        cg_host = 'host@backend#unit_test_pool'
        volumes = [cinder_input['vol1']]
        cgsnap_id = fake_constants.CGSNAPSHOT_ID
        snaps = [cinder_input['snap1']]

        model_update, volume_updates = (
            vnx_common.do_create_cg_from_cgsnap(
                cg_id, cg_host, volumes, cgsnap_id, snaps))
        self.assertIsNone(model_update)
        provider_location = re.findall('id\^12',
                                       volume_updates[0]['provider_location'])
        self.assertEqual(1, len(provider_location))

    @res_mock.patch_common_adapter
    def test_create_cloned_cg(self, common, _):
        common.do_clone_cg = mock.Mock(
            return_value='fake_return')
        group = test_utils.create_consistencygroup(
            self.ctxt,
            id=fake_constants.CONSISTENCY_GROUP_ID,
            host='host@backend#unit_test_pool',
            group_type_id=fake_constants.VOLUME_TYPE_ID)
        src_group = test_utils.create_consistencygroup(
            self.ctxt,
            id=fake_constants.CONSISTENCY_GROUP2_ID,
            host='host@backend#unit_test_pool2',
            group_type_id=fake_constants.VOLUME_TYPE_ID)
        vol = test_utils.create_volume(self.ctxt)
        src_vol = test_utils.create_volume(self.ctxt)
        ret = common.create_cloned_group(
            None, group, [vol], src_group, [src_vol])
        self.assertEqual('fake_return', ret)
        common.do_clone_cg.assert_called_once_with(
            group.id, group.host, [vol], src_group.id, [src_vol])

    @res_mock.patch_common_adapter
    def test_create_cloned_group(self, common, _):
        common.do_clone_cg = mock.Mock(
            return_value='fake_return')
        group = test_utils.create_group(
            self.ctxt,
            id=fake_constants.GROUP_ID,
            host='host@backend#unit_test_pool',
            group_type_id=fake_constants.VOLUME_TYPE_ID)
        src_group = test_utils.create_group(
            self.ctxt,
            id=fake_constants.GROUP2_ID,
            host='host@backend#unit_test_pool2',
            group_type_id=fake_constants.VOLUME_TYPE_ID)
        vol = test_utils.create_volume(self.ctxt)
        src_vol = test_utils.create_volume(self.ctxt)
        ret = common.create_cloned_group(
            None, group, [vol], src_group, [src_vol])
        self.assertEqual('fake_return', ret)
        common.do_clone_cg.assert_called_once_with(
            group.id, group.host, [vol], src_group.id, [src_vol])

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_do_clone_cg(self, vnx_common, _, cinder_input):
        cg_id = fake_constants.CONSISTENCY_GROUP_ID
        cg_host = 'host@backend#unit_test_pool'
        volumes = [cinder_input['vol1']]
        src_cg_id = fake_constants.CONSISTENCY_GROUP2_ID
        src_volumes = [cinder_input['src_vol1']]
        model_update, volume_updates = vnx_common.do_clone_cg(
            cg_id, cg_host, volumes, src_cg_id, src_volumes)
        self.assertIsNone(model_update)
        provider_location = re.findall('id\^12',
                                       volume_updates[0]['provider_location'])
        self.assertEqual(1, len(provider_location))

    @res_mock.patch_common_adapter
    def test_parse_pools(self, vnx_common, mocked):
        vnx_common.config.storage_vnx_pool_names = ['pool5', 'pool6']
        parsed = vnx_common.parse_pools()
        self.assertEqual(
            len(vnx_common.config.storage_vnx_pool_names),
            len(parsed))
        pools = vnx_common.client.get_pools()
        self.assertEqual(pools, parsed)

    @res_mock.patch_common_adapter
    def test_parse_pools_one_invalid_pool(self, vnx_common, mocked):
        vnx_common.config.storage_vnx_pool_names = ['pool5', 'pool7']
        parsed = vnx_common.parse_pools()
        pools = vnx_common.client.get_pools()
        self.assertIn(parsed[0], pools)

    @res_mock.patch_common_adapter
    def test_parse_pools_all_invalid_pools(self, vnx_common, mocked):
        vnx_common.config.storage_vnx_pool_names = ['pool7', 'pool8']
        self.assertRaises(exception.VolumeBackendAPIException,
                          vnx_common.parse_pools)

    @res_mock.patch_common_adapter
    def test_get_enabler_stats(self, vnx_common, mocked):
        stats = vnx_common.get_enabler_stats()
        self.assertTrue(stats['compression_support'])
        self.assertTrue(stats['fast_support'])
        self.assertTrue(stats['deduplication_support'])
        self.assertTrue(stats['thin_provisioning_support'])
        self.assertTrue(stats['consistent_group_snapshot_enabled'])

    @res_mock.patch_common_adapter
    def test_get_pool_stats(self, vnx_common, mocked):
        pools = vnx_common.client.vnx.get_pool()
        vnx_common.config.storage_vnx_pool_names = [
            pool.name for pool in pools]
        stats = {
            'compression_support': True,
            'fast_support': True,
            'deduplication_support': True,
            'thin_provisioning_support': True,
            'consistent_group_snapshot_enabled': True,
            'consistencygroup_support': True

        }
        pool_stats = vnx_common.get_pool_stats(stats)
        self.assertEqual(2, len(pool_stats))
        for stat in pool_stats:
            self.assertTrue(stat['fast_cache_enabled'])
            self.assertTrue(stat['QoS_support'])
            self.assertIn(stat['pool_name'], [pools[0].name,
                                              pools[1].name])
            self.assertFalse(stat['replication_enabled'])
            self.assertEqual([], stat['replication_targets'])

    @res_mock.patch_common_adapter
    def test_get_pool_stats_offline(self, vnx_common, mocked):
        vnx_common.config.storage_vnx_pool_names = []
        pool_stats = vnx_common.get_pool_stats()
        for stat in pool_stats:
            self.assertTrue(stat['fast_cache_enabled'])
            self.assertEqual(0, stat['free_capacity_gb'])

    @res_mock.patch_common_adapter
    def test_get_pool_stats_max_luns_reached(self, vnx_common, mocked):
        pools = vnx_common.client.vnx.get_pool()
        vnx_common.config.storage_vnx_pool_names = [
            pool.name for pool in pools]
        stats = {
            'compression_support': True,
            'fast_support': True,
            'deduplication_support': True,
            'thin_provisioning_support': True,
            'consistent_group_snapshot_enabled': True,
            'consistencygroup_support': True

        }
        pool_stats = vnx_common.get_pool_stats(stats)
        for stat in pool_stats:
            self.assertTrue(stat['fast_cache_enabled'])
            self.assertEqual(0, stat['free_capacity_gb'])

    @res_mock.patch_common_adapter
    def test_get_pool_stats_with_reserved(self, vnx_common, mocked):
        pools = vnx_common.client.vnx.get_pool()
        vnx_common.config.storage_vnx_pool_names = [
            pool.name for pool in pools]
        stats = {
            'compression_support': True,
            'fast_support': True,
            'deduplication_support': True,
            'thin_provisioning_support': True,
            'consistent_group_snapshot_enabled': True,
            'consistencygroup_support': True

        }
        vnx_common.reserved_percentage = 15
        pool_stats = vnx_common.get_pool_stats(stats)
        for stat in pool_stats:
            self.assertTrue(stat['fast_cache_enabled'])
            self.assertIsNot(0, stat['free_capacity_gb'])
            self.assertEqual(15, stat['reserved_percentage'])

    @res_mock.patch_common_adapter
    def test_update_volume_stats(self, vnx_common, mocked):
        with mock.patch.object(adapter.CommonAdapter, 'get_pool_stats'):
            stats = vnx_common.update_volume_stats()
        pools_stats = stats['pools']
        for stat in pools_stats:
            self.assertFalse(stat['replication_enabled'])
            self.assertEqual([], stat['replication_targets'])

    @res_mock.patch_common_adapter
    def test_append_volume_stats(self, vnx_common, mocked):
        device = utils.get_replication_device()
        vnx_common.config.replication_device = [device]
        vnx_common.mirror_view = utils.build_fake_mirror_view()
        stats = {}
        vnx_common.append_replication_stats(stats)
        self.assertTrue(stats['replication_enabled'])
        self.assertEqual(1, stats['replication_count'])
        self.assertEqual(['sync'], stats['replication_type'])
        self.assertEqual([device['backend_id']],
                         stats['replication_targets'])

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_delete_volume_not_force(self, vnx_common, mocked, mocked_input):
        vnx_common.force_delete_lun_in_sg = False
        volume = mocked_input['volume']
        volume['metadata'] = {'async_migrate': 'False'}
        vnx_common.delete_volume(volume)
        lun = vnx_common.client.vnx.get_lun()
        lun.delete.assert_called_with(force_detach=True, detach_from_sg=False)

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_delete_volume_force(self, vnx_common, mocked, mocked_input):
        vnx_common.force_delete_lun_in_sg = True
        volume = mocked_input['volume']
        volume['metadata'] = {'async_migrate': 'False'}
        vnx_common.delete_volume(volume)
        lun = vnx_common.client.vnx.get_lun()
        lun.delete.assert_called_with(force_detach=True, detach_from_sg=True)

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_delete_async_volume(self, vnx_common, mocked, mocked_input):
        volume = mocked_input['volume']
        volume.metadata = {'async_migrate': 'True'}
        vnx_common.force_delete_lun_in_sg = True
        vnx_common.delete_volume(volume)
        lun = vnx_common.client.vnx.get_lun()
        lun.delete.assert_called_with(force_detach=True, detach_from_sg=True)

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_delete_async_volume_migrating(self, vnx_common, mocked,
                                           mocked_input):

        volume = mocked_input['volume']
        volume.metadata = {'async_migrate': 'True'}
        vnx_common.force_delete_lun_in_sg = True
        vnx_common.client.cleanup_async_lun = mock.Mock()
        vnx_common.delete_volume(volume)
        lun = vnx_common.client.vnx.get_lun()
        lun.delete.assert_called_with(force_detach=True, detach_from_sg=True)

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_delete_async_volume_not_from_snapshot(self, vnx_common, mocked,
                                                   mocked_input):
        volume = mocked_input['volume']
        volume.metadata = {'async_migrate': 'True'}
        vnx_common.force_delete_lun_in_sg = True
        vnx_common.delete_volume(volume)
        lun = vnx_common.client.vnx.get_lun()
        lun.delete.assert_called_with(force_detach=True, detach_from_sg=True)

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_delete_async_volume_from_snapshot(self, vnx_common, mocked,
                                               mocked_input):
        volume = mocked_input['volume']
        volume.metadata = {'async_migrate': 'True'}
        volume.snapshot_id = 'snap'
        vnx_common.force_delete_lun_in_sg = True
        vnx_common.delete_volume(volume)
        lun = vnx_common.client.vnx.get_lun()
        lun.delete.assert_called_with(force_detach=True, detach_from_sg=True)
        snap = vnx_common.client.vnx.get_snap()
        snap.delete.assert_called_with()

    @utils.patch_extra_specs_validate(side_effect=exception.InvalidVolumeType(
        reason='fake_reason'))
    @res_mock.patch_common_adapter
    def test_retype_type_invalid(self, vnx_common, mocked):
        self.assertRaises(exception.InvalidVolumeType,
                          vnx_common.retype,
                          None, None,
                          {'extra_specs': 'fake_spec'},
                          None, None)

    @mock.patch.object(client.Client, 'get_vnx_enabler_status')
    @utils.patch_extra_specs_validate(return_value=True)
    @utils.patch_extra_specs({'storagetype:tiering': 'auto',
                              'provisioning:type': 'thin'})
    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_retype_need_migration(
            self, vnx_common, mocked, driver_in,
            enabler_status):
        new_type = {
            'extra_specs': {'provisioning:type': 'deduplicated',
                            'storagetype:tiering': 'starthighthenauto'}}
        volume = driver_in['volume']
        host = driver_in['host']
        fake_migrate_return = (True, ['fake_model_update'])
        vnx_common._migrate_volume = mock.Mock(
            return_value=fake_migrate_return)
        ret = vnx_common.retype(None, volume, new_type, None, host)
        self.assertEqual(fake_migrate_return, ret)
        vnx_common._migrate_volume.assert_called_once_with(
            volume, host, common.ExtraSpecs(new_type['extra_specs']))

    @mock.patch.object(client.Client, 'get_vnx_enabler_status')
    @utils.patch_extra_specs_validate(return_value=True)
    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_retype_turn_on_compression_change_tier(
            self, vnx_common, mocked, driver_in,
            enabler_status):
        new_type = {
            'extra_specs': {'provisioning:type': 'compressed',
                            'storagetype:tiering': 'starthighthenauto'}}
        volume = driver_in['volume']
        host = driver_in['host']
        lun = mocked['lun']
        vnx_common.client.get_lun = mock.Mock(return_value=lun)
        ret = vnx_common.retype(None, volume, new_type, None, host)
        self.assertTrue(ret)
        lun.enable_compression.assert_called_once_with(ignore_thresholds=True)
        self.assertEqual(storops.VNXTieringEnum.HIGH_AUTO, lun.tier)

    @mock.patch.object(client.Client, 'get_vnx_enabler_status')
    @utils.patch_extra_specs_validate(return_value=True)
    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_retype_lun_has_snap(
            self, vnx_common, mocked, driver_in,
            enabler_status):
        new_type = {
            'extra_specs': {'provisioning:type': 'thin',
                            'storagetype:tiering': 'auto'}}
        volume = driver_in['volume']
        host = driver_in['host']
        new_type = {
            'extra_specs': {'provisioning:type': 'thin',
                            'storagetype:tiering': 'auto'}}
        ret = vnx_common.retype(None, volume, new_type, None, host)
        self.assertFalse(ret)
        new_type = {
            'extra_specs': {'provisioning:type': 'compressed',
                            'storagetype:tiering': 'auto'}}
        ret = vnx_common.retype(None, volume, new_type, None, host)
        self.assertFalse(ret)

    @mock.patch.object(client.Client, 'get_vnx_enabler_status')
    @utils.patch_extra_specs_validate(return_value=True)
    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_retype_change_tier(
            self, vnx_common, mocked, driver_in,
            enabler_status):
        new_type = {
            'extra_specs': {'storagetype:tiering': 'auto'}}
        volume = driver_in['volume']
        host = driver_in['host']
        lun = mocked['lun']
        vnx_common.client.get_lun = mock.Mock(return_value=lun)
        ret = vnx_common.retype(None, volume, new_type, None, host)
        self.assertTrue(ret)
        self.assertEqual(storops.VNXTieringEnum.AUTO, lun.tier)

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_create_consistencygroup(self, vnx_common, mocked, mocked_input):
        cg = mocked_input['cg']
        model_update = vnx_common.create_consistencygroup(None, group=cg)
        self.assertEqual(fields.ConsistencyGroupStatus.AVAILABLE,
                         model_update['status'])

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_delete_consistencygroup(self, vnx_common, mocked, mocked_input):
        cg = mocked_input['cg']
        model_update, vol_update_list = vnx_common.delete_consistencygroup(
            None, group=cg, volumes=[])
        self.assertEqual(cg.status,
                         model_update['status'])
        self.assertEqual([], vol_update_list)

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_delete_consistencygroup_with_volume(
            self, vnx_common, mocked, mocked_input):
        cg = mocked_input['cg']
        vol1 = mocked_input['vol1']
        vol2 = mocked_input['vol2']
        model_update, vol_update_list = vnx_common.delete_consistencygroup(
            None, group=cg, volumes=[vol1, vol2])
        self.assertEqual(cg.status,
                         model_update['status'])
        for update in vol_update_list:
            self.assertEqual(fields.ConsistencyGroupStatus.DELETED,
                             update['status'])

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_delete_consistencygroup_error(self, vnx_common,
                                           mocked, mocked_input):
        cg = mocked_input['cg']
        self.assertRaises(
            storops_ex.VNXConsistencyGroupError,
            vnx_common.delete_consistencygroup,
            context=None, group=cg, volumes=[])

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_delete_consistencygroup_volume_error(self, vnx_common,
                                                  mocked, mocked_input):
        cg = mocked_input['cg']
        vol1 = mocked_input['vol1']
        vol2 = mocked_input['vol2']
        model_update, vol_update_list = vnx_common.delete_consistencygroup(
            None, group=cg, volumes=[vol1, vol2])
        self.assertEqual(cg.status,
                         model_update['status'])
        for update in vol_update_list:
            self.assertEqual(fields.ConsistencyGroupStatus.ERROR_DELETING,
                             update['status'])

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_extend_volume(self, common_adapter, _ignore, mocked_input):
        common_adapter.extend_volume(mocked_input['volume'], 10)

        lun = common_adapter.client.vnx.get_lun()
        lun.expand.assert_called_once_with(10, ignore_thresholds=True)

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_create_snapshot_adapter(self, common_adapter, _ignore,
                                     mocked_input):
        common_adapter.create_snapshot(mocked_input['snapshot'])

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_delete_snapshot_adapter(self, common_adapter, _ignore,
                                     mocked_input):
        common_adapter.delete_snapshot(mocked_input['snapshot'])

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_restore_snapshot_adapter(self, common_adapter, _ignore,
                                      mocked_input):
        common_adapter.restore_snapshot(mocked_input['volume'],
                                        mocked_input['snapshot'])

    @res_mock.patch_common_adapter
    def test_create_cgsnapshot(self, common_adapter, _):
        common_adapter.do_create_cgsnap = mock.Mock(
            return_value='fake_return')
        cg_snapshot = test_utils.create_cgsnapshot(
            self.ctxt,
            fake_constants.CONSISTENCY_GROUP_ID)
        vol = test_utils.create_volume(self.ctxt)
        snaps = [
            test_utils.create_snapshot(self.ctxt, vol.id)]
        ret = common_adapter.create_cgsnapshot(
            None, cg_snapshot, snaps)
        self.assertEqual('fake_return', ret)
        common_adapter.do_create_cgsnap.assert_called_once_with(
            cg_snapshot.consistencygroup_id,
            cg_snapshot.id,
            snaps)

    @res_mock.patch_common_adapter
    def test_create_group_snap(self, common_adapter, _):
        common_adapter.do_create_cgsnap = mock.Mock(
            return_value='fake_return')
        group_snapshot = test_utils.create_group_snapshot(
            self.ctxt,
            fake_constants.GROUP_ID,
            group_type_id=fake_constants.VOLUME_TYPE_ID)
        vol = test_utils.create_volume(self.ctxt)
        snaps = [
            test_utils.create_snapshot(self.ctxt, vol.id)]
        ret = common_adapter.create_group_snapshot(
            None, group_snapshot, snaps)
        self.assertEqual('fake_return', ret)
        common_adapter.do_create_cgsnap.assert_called_once_with(
            group_snapshot.group_id,
            group_snapshot.id,
            snaps)

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_do_create_cgsnap(self, common_adapter, _, mocked_input):
        group_name = fake_constants.CONSISTENCY_GROUP_ID
        snap_name = fake_constants.CGSNAPSHOT_ID
        snap1 = mocked_input['snap1']
        snap2 = mocked_input['snap2']
        model_update, snapshots_model_update = (
            common_adapter.do_create_cgsnap(group_name, snap_name,
                                            [snap1, snap2]))
        self.assertEqual('available', model_update['status'])
        for update in snapshots_model_update:
            self.assertEqual(fields.SnapshotStatus.AVAILABLE, update['status'])

    @res_mock.patch_common_adapter
    def test_delete_group_snapshot(self, common_adapter, _):
        common_adapter.do_delete_cgsnap = mock.Mock(
            return_value='fake_return')
        group_snapshot = test_utils.create_group_snapshot(
            self.ctxt,
            fake_constants.GROUP_ID,
            group_type_id=fake_constants.VOLUME_TYPE_ID)
        vol = test_utils.create_volume(self.ctxt)
        snaps = [
            test_utils.create_snapshot(self.ctxt, vol.id)]
        ret = common_adapter.delete_group_snapshot(
            None, group_snapshot, snaps)
        self.assertEqual('fake_return', ret)
        common_adapter.do_delete_cgsnap.assert_called_once_with(
            group_snapshot.group_id,
            group_snapshot.id,
            group_snapshot.status,
            snaps)

    @res_mock.patch_common_adapter
    def test_delete_cgsnapshot(self, common_adapter, _):
        common_adapter.do_delete_cgsnap = mock.Mock(
            return_value='fake_return')
        cg_snapshot = test_utils.create_cgsnapshot(
            self.ctxt,
            fake_constants.CONSISTENCY_GROUP_ID)
        vol = test_utils.create_volume(self.ctxt)
        snaps = [
            test_utils.create_snapshot(self.ctxt, vol.id)]
        ret = common_adapter.delete_cgsnapshot(None, cg_snapshot, snaps)
        self.assertEqual('fake_return', ret)
        common_adapter.do_delete_cgsnap.assert_called_once_with(
            cg_snapshot.consistencygroup_id,
            cg_snapshot.id,
            cg_snapshot.status,
            snaps)

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_do_delete_cgsnap(self, common_adapter, _, mocked_input):
        group_name = fake_constants.CGSNAPSHOT_ID
        snap_name = fake_constants.CGSNAPSHOT_ID
        model_update, snapshot_updates = (
            common_adapter.do_delete_cgsnap(
                group_name, snap_name, 'available',
                [mocked_input['snap1'], mocked_input['snap2']]))
        self.assertEqual('deleted', model_update['status'])
        for snap in snapshot_updates:
            self.assertEqual(fields.SnapshotStatus.DELETED, snap['status'])

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_manage_existing_lun_no_exist(
            self, common_adapter, _ignore, mocked_input):
        self.assertRaises(
            exception.ManageExistingInvalidReference,
            common_adapter.manage_existing_get_size,
            mocked_input['volume'], {'source-name': 'fake'})
        common_adapter.client.vnx.get_lun.assert_called_once_with(
            name='fake', lun_id=None)

    @res_mock.patch_common_adapter
    def test_manage_existing_invalid_ref(
            self, common_adapter, _ignore):
        self.assertRaises(
            exception.ManageExistingInvalidReference,
            common_adapter.manage_existing_get_size,
            None, {'invalidkey': 'fake'})

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_manage_existing_invalid_pool(
            self, common_adapter, _ignore, mocked_input):
        self.assertRaises(
            exception.ManageExistingInvalidReference,
            common_adapter.manage_existing_get_size,
            mocked_input['volume'], {'source-id': '6'})
        common_adapter.client.vnx.get_lun.assert_called_once_with(
            lun_id='6', name=None)

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_manage_existing_get_size(
            self, common_adapter, mocked_res, mocked_input):
        size = common_adapter.manage_existing_get_size(
            mocked_input['volume'], {'source-name': 'test_lun'})
        self.assertEqual(size, mocked_res['lun'].total_capacity_gb)

    @utils.patch_extra_specs({'provisioning:type': 'thin',
                              'storagetype:tiering': 'auto'})
    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_manage_existing_type_mismatch(
            self, common_adapter, mocked_res, mocked_input):
        self.assertRaises(exception.ManageExistingVolumeTypeMismatch,
                          common_adapter.manage_existing,
                          mocked_input['volume'],
                          {'source-name': 'test_lun'})

    @utils.patch_extra_specs({'provisioning:type': 'deduplicated'})
    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_manage_existing(
            self, common_adapter, mocked_res, mocked_input):
        test_lun = mocked_res['lun']
        common_adapter.client.get_lun = mock.Mock(return_value=test_lun)
        lun_name = mocked_input['volume'].name
        common_adapter._build_provider_location = mock.Mock(
            return_value="fake_pl")
        pl = common_adapter.manage_existing(
            mocked_input['volume'],
            {'source-name': 'test_lun'})
        common_adapter._build_provider_location.assert_called_with(
            lun_type='lun',
            lun_id=1,
            base_lun_name=lun_name)
        self.assertEqual('fake_pl', pl['provider_location'])
        test_lun.rename.assert_called_once_with(
            lun_name)

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_manage_existing_smp(
            self, common_adapter, mocked_res, mocked_input):
        common_adapter._build_provider_location = mock.Mock(
            return_value="fake_pl")
        pl = common_adapter.manage_existing(
            mocked_input['volume'], {'source-name': 'test_lun'})
        common_adapter._build_provider_location.assert_called_with(
            lun_id=2, lun_type='smp', base_lun_name='src_lun')
        self.assertEqual('fake_pl', pl['provider_location'])

    @res_mock.patch_common_adapter
    def test_assure_storage_group(self, common_adapter, mocked_res):
        host = common.Host('host', ['initiators'])
        common_adapter.assure_storage_group(host)

    @res_mock.patch_common_adapter
    def test_assure_storage_group_create_new(self, common_adapter, mocked_res):
        host = common.Host('host', ['initiators'])
        common_adapter.assure_storage_group(host)
        common_adapter.client.vnx.create_sg.assert_called_once_with(host.name)

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_assure_host_access(self, common_adapter,
                                mocked_res, mocked_input):
        common_adapter.config.initiator_auto_registration = True
        common_adapter.max_retries = 3
        common_adapter.auto_register_initiator = mock.Mock()
        common_adapter.client.add_lun_to_sg = mock.Mock()
        sg = mocked_res['sg']
        host = common.Host('host', ['initiators'])
        cinder_volume = mocked_input['volume']
        volume = common.Volume(cinder_volume.name, cinder_volume.id,
                               common_adapter.client.get_lun_id(cinder_volume))
        lun = common_adapter.client.get_lun()
        common_adapter.assure_host_access(sg, host, volume, True)
        common_adapter.auto_register_initiator.assert_called_once_with(
            sg, host)
        common_adapter.client.add_lun_to_sg.assert_called_once_with(
            sg, lun, common_adapter.max_retries)

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_assure_host_access_without_auto_register_new_sg(
            self, common_adapter, mocked_res, mocked_input):
        common_adapter.config.initiator_auto_registration = False
        common_adapter.max_retries = 3
        common_adapter.client.add_lun_to_sg = mock.Mock()
        sg = mocked_res['sg']
        host = common.Host('host', ['initiators'])
        cinder_volume = mocked_input['volume']
        volume = common.Volume(cinder_volume.name, cinder_volume.id,
                               common_adapter.client.get_lun_id(cinder_volume))
        lun = common_adapter.client.get_lun()
        common_adapter.assure_host_access(sg, host, volume, True)
        sg.connect_host.assert_called_once_with(host.name)
        common_adapter.client.add_lun_to_sg.assert_called_once_with(
            sg, lun, common_adapter.max_retries)

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_assure_host_access_without_auto_register(
            self, common_adapter, mocked_res, mocked_input):
        common_adapter.config.initiator_auto_registration = False
        common_adapter.max_retries = 3
        common_adapter.client.add_lun_to_sg = mock.Mock()
        sg = mocked_res['sg']
        host = common.Host('host', ['initiators'])
        cinder_volume = mocked_input['volume']
        volume = common.Volume(cinder_volume.name, cinder_volume.id,
                               common_adapter.client.get_lun_id(cinder_volume))
        lun = common_adapter.client.get_lun()
        common_adapter.assure_host_access(sg, host, volume, False)
        sg.connect_host.assert_not_called()
        common_adapter.client.add_lun_to_sg.assert_called_once_with(
            sg, lun, common_adapter.max_retries)

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_auto_register_initiator(
            self, common_adapter, mocked_res, mocked_input):
        common_adapter.client.register_initiator = mock.Mock()

        common_adapter.config.io_port_list = ['a-0-0', 'a-0-1', 'a-1-0',
                                              'b-0-1']
        allowed_ports = mocked_res['allowed_ports']
        common_adapter.allowed_ports = allowed_ports
        reg_ports = mocked_res['reg_ports']
        sg = mocked_res['sg']
        host = common.Host('host', ['iqn-host-1', 'iqn-reg-2'])
        common_adapter.auto_register_initiator(sg, host)

        initiator_port_map = {'iqn-host-1': set(allowed_ports),
                              'iqn-reg-2': set(allowed_ports) - set(reg_ports)}
        common_adapter.client.register_initiator.assert_called_once_with(
            sg, host, initiator_port_map)

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_auto_register_initiator_no_white_list(
            self, common_adapter, mocked_res, mocked_input):
        for io_port_list in (None, ):
            common_adapter.client.register_initiator = mock.Mock()

            common_adapter.config.io_port_list = io_port_list
            allowed_ports = mocked_res['allowed_ports']
            common_adapter.allowed_ports = allowed_ports
            sg = mocked_res['sg']
            host = common.Host('host', ['iqn-host-1', 'iqn-reg-2'])
            common_adapter.auto_register_initiator(sg, host)

            initiator_port_map = {'iqn-host-1': set(allowed_ports)}
            common_adapter.client.register_initiator.assert_called_once_with(
                sg, host, initiator_port_map)

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_auto_register_initiator_no_port_to_reg(
            self, common_adapter, mocked_res, mocked_input):
        common_adapter.config.io_port_list = ['a-0-0']
        allowed_ports = mocked_res['allowed_ports']
        common_adapter.allowed_ports = allowed_ports
        sg = mocked_res['sg']
        host = common.Host('host', ['iqn-reg-1', 'iqn-reg-2'])
        with mock.patch.object(common_adapter.client, 'register_initiator'):
            common_adapter.auto_register_initiator(sg, host)
            common_adapter.client.register_initiator.assert_called_once_with(
                sg, host, {})

    @res_mock.patch_common_adapter
    def test_build_provider_location(self, common_adapter, mocked_res):
        common_adapter.serial_number = 'vnx-serial'
        pl = common_adapter._build_provider_location(
            lun_id='fake_id', lun_type='smp', base_lun_name='fake_name')
        expected_pl = vnx_utils.build_provider_location(
            system='vnx-serial',
            lun_type='smp',
            lun_id='fake_id',
            base_lun_name='fake_name',
            version=common_adapter.VERSION)
        self.assertEqual(expected_pl, pl)

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_remove_host_access(
            self, common_adapter, mocked_res, mocked_input):
        host = common.Host('fake_host', ['fake_initiator'])
        cinder_volume = mocked_input['volume']
        volume = common.Volume(cinder_volume.name, cinder_volume.id,
                               common_adapter.client.get_lun_id(cinder_volume))
        sg = mocked_res['sg']
        common_adapter.remove_host_access(volume, host, sg)

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_remove_host_access_sg_absent(
            self, common_adapter, mocked_res, mocked_input):
        host = common.Host('fake_host', ['fake_initiator'])
        cinder_volume = mocked_input['volume']
        volume = common.Volume(cinder_volume.name, cinder_volume.id,
                               common_adapter.client.get_lun_id(cinder_volume))
        sg = mocked_res['sg']
        common_adapter.remove_host_access(volume, host, sg)

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_remove_host_access_volume_not_in_sg(
            self, common_adapter, mocked_res, mocked_input):
        host = common.Host('fake_host', ['fake_initiator'])
        cinder_volume = mocked_input['volume']
        volume = common.Volume(cinder_volume.name, cinder_volume.id,
                               common_adapter.client.get_lun_id(cinder_volume))
        sg = mocked_res['sg']
        common_adapter.remove_host_access(volume, host, sg)

    @res_mock.patch_common_adapter
    def test_terminate_connection_cleanup_sg_absent(
            self, common_adapter, mocked_res):
        common_adapter.destroy_empty_sg = True
        common_adapter.itor_auto_dereg = True
        host = common.Host('fake_host', ['fake_initiator'])
        sg = mocked_res['sg']
        common_adapter.terminate_connection_cleanup(host, sg)

    @res_mock.patch_common_adapter
    def test_terminate_connection_cleanup_remove_sg(
            self, common_adapter, mocked_res):
        common_adapter.destroy_empty_sg = True
        common_adapter.itor_auto_dereg = False
        host = common.Host('fake_host', ['fake_initiator'])
        sg = mocked_res['sg']
        common_adapter.terminate_connection_cleanup(host, sg)

    @res_mock.patch_common_adapter
    def test_terminate_connection_cleanup_deregister(
            self, common_adapter, mocked_res):
        common_adapter.destroy_empty_sg = True
        common_adapter.itor_auto_dereg = True
        host = common.Host('fake_host', ['fake_initiator1', 'fake_initiator2'])
        sg = mocked_res['sg']
        common_adapter.terminate_connection_cleanup(host, sg)
        common_adapter.client.vnx.delete_hba.assert_any_call(
            'fake_initiator1')
        common_adapter.client.vnx.delete_hba.assert_any_call(
            'fake_initiator2')

    @res_mock.patch_common_adapter
    def test_terminate_connection_cleanup_sg_is_not_empty(
            self, common_adapter, mocked_res):
        common_adapter.destroy_empty_sg = True
        common_adapter.itor_auto_dereg = True
        host = common.Host('fake_host', ['fake_initiator'])
        sg = mocked_res['sg']
        common_adapter.terminate_connection_cleanup(host, sg)

    @res_mock.patch_common_adapter
    def test_set_extra_spec_defaults(self, common_adapter, mocked_res):
        common_adapter.set_extra_spec_defaults()
        self.assertEqual(storops.VNXTieringEnum.HIGH_AUTO,
                         common.ExtraSpecs.TIER_DEFAULT)

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_do_update_cg(self, common_adapter, _, mocked_input):
        common_adapter.client.update_consistencygroup = mock.Mock()
        cg = mocked_input['cg']
        common_adapter.client.get_cg = mock.Mock(return_value=cg)
        common_adapter.do_update_cg(cg.id,
                                    [mocked_input['volume_add']],
                                    [mocked_input['volume_remove']])

        common_adapter.client.update_consistencygroup.assert_called_once_with(
            cg, [1], [2])

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_create_export_snapshot(self, common_adapter, mocked_res,
                                    mocked_input):
        common_adapter.client.create_mount_point = mock.Mock()
        snapshot = mocked_input['snapshot']
        common_adapter.create_export_snapshot(None, snapshot, None)
        common_adapter.client.create_mount_point.assert_called_once_with(
            snapshot.volume_name, 'tmp-smp-' + snapshot.id)

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_remove_export_snapshot(self, common_adapter, mocked_res,
                                    mocked_input):
        common_adapter.client.delete_lun = mock.Mock()
        snapshot = mocked_input['snapshot']
        common_adapter.remove_export_snapshot(None, snapshot)
        common_adapter.client.delete_lun.assert_called_once_with(
            'tmp-smp-' + snapshot.id)

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_initialize_connection_snapshot(self, common_adapter, mocked_res,
                                            mocked_input):
        common_adapter.client.attach_snapshot = mock.Mock()
        common_adapter._initialize_connection = mock.Mock(return_value='fake')

        snapshot = mocked_input['snapshot']
        smp_name = 'tmp-smp-' + snapshot.id
        conn = common_adapter.initialize_connection_snapshot(snapshot, None)
        common_adapter.client.attach_snapshot.assert_called_once_with(
            smp_name, snapshot.name)
        lun = mocked_res['lun']
        called_volume = common_adapter._initialize_connection.call_args[0][0]
        self.assertEqual((smp_name, snapshot.id, lun.lun_id),
                         (called_volume.name, called_volume.id,
                             called_volume.vnx_lun_id))
        self.assertIsNone(
            common_adapter._initialize_connection.call_args[0][1])
        self.assertIs(common_adapter._initialize_connection(), conn)

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_terminate_connection_snapshot(self, common_adapter, mocked_res,
                                           mocked_input):
        common_adapter.client.detach_snapshot = mock.Mock()
        common_adapter._terminate_connection = mock.Mock()

        snapshot = mocked_input['snapshot']
        smp_name = 'tmp-smp-' + snapshot.id
        common_adapter.terminate_connection_snapshot(snapshot, None)
        lun = mocked_res['lun']
        called_volume = common_adapter._terminate_connection.call_args[0][0]
        self.assertEqual((smp_name, snapshot.id, lun.lun_id),
                         (called_volume.name, called_volume.id,
                             called_volume.vnx_lun_id))
        self.assertIsNone(common_adapter._terminate_connection.call_args[0][1])
        common_adapter.client.detach_snapshot.assert_called_once_with(
            smp_name)

    @utils.patch_extra_specs({'replication_enabled': '<is> True'})
    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_setup_lun_replication(self, common_adapter,
                                   mocked_res, mocked_input):
        vol1 = mocked_input['vol1']
        fake_mirror = utils.build_fake_mirror_view()
        fake_mirror.secondary_client.create_lun.return_value = (
            mocked_res['lun'])
        common_adapter.mirror_view = fake_mirror
        common_adapter.config.replication_device = (
            [utils.get_replication_device()])
        rep_update = common_adapter.setup_lun_replication(
            vol1, 111)
        fake_mirror.create_mirror.assert_called_once_with(
            'mirror_' + vol1.id, 111)
        fake_mirror.add_image.assert_called_once_with(
            'mirror_' + vol1.id, mocked_res['lun'].lun_id)
        self.assertEqual(fields.ReplicationStatus.ENABLED,
                         rep_update['replication_status'])

    @utils.patch_extra_specs({'replication_enabled': '<is> True'})
    @utils.patch_group_specs({'consistent_group_replication_enabled':
                              '<is> True'})
    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_setup_lun_replication_in_group(
            self, common_adapter, mocked_res, mocked_input):
        vol1 = mocked_input['vol1']
        group1 = mocked_input['group1']
        vol1.group = group1
        fake_mirror = utils.build_fake_mirror_view()
        fake_mirror.secondary_client.create_lun.return_value = (
            mocked_res['lun'])
        common_adapter.mirror_view = fake_mirror
        common_adapter.config.replication_device = (
            [utils.get_replication_device()])
        rep_update = common_adapter.setup_lun_replication(
            vol1, 111)
        fake_mirror.create_mirror.assert_called_once_with(
            'mirror_' + vol1.id, 111)
        fake_mirror.add_image.assert_called_once_with(
            'mirror_' + vol1.id, mocked_res['lun'].lun_id)
        self.assertEqual(fields.ReplicationStatus.ENABLED,
                         rep_update['replication_status'])

    @utils.patch_extra_specs({'replication_enabled': '<is> True'})
    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_cleanup_replication(self, common_adapter,
                                 mocked_res, mocked_input):
        fake_mirror = utils.build_fake_mirror_view()
        vol1 = mocked_input['vol1']
        with mock.patch.object(common_adapter, 'build_mirror_view') as fake:
            fake.return_value = fake_mirror
            common_adapter.cleanup_lun_replication(vol1)
            fake_mirror.destroy_mirror.assert_called_once_with(
                'mirror_' + vol1.id, vol1.name)

    @res_mock.patch_common_adapter
    def test_build_mirror_view(self, common_adapter,
                               mocked_res):
        common_adapter.config.replication_device = [
            utils.get_replication_device()]
        with utils.patch_vnxsystem:
            mirror = common_adapter.build_mirror_view(
                common_adapter.config)
        self.assertIsNotNone(mirror)

    @res_mock.patch_common_adapter
    def test_build_mirror_view_no_device(
            self, common_adapter, mocked_res):
        common_adapter.config.replication_device = []
        mirror = common_adapter.build_mirror_view(
            common_adapter.config)
        self.assertIsNone(mirror)

    @res_mock.patch_common_adapter
    def test_build_mirror_view_2_device(self, common_adapter, mocked_res):
        device = utils.get_replication_device()
        device1 = device.copy()
        common_adapter.config.replication_device = [device, device1]
        self.assertRaises(exception.InvalidInput,
                          common_adapter.build_mirror_view,
                          common_adapter.config)

    @res_mock.patch_common_adapter
    def test_build_mirror_view_no_enabler(self, common_adapter, mocked_res):
        common_adapter.config.replication_device = [
            utils.get_replication_device()]
        self.assertRaises(exception.InvalidInput,
                          common_adapter.build_mirror_view,
                          common_adapter.config)

    @res_mock.patch_common_adapter
    def test_build_mirror_view_failover_false(self, common_adapter,
                                              mocked_res):
        common_adapter.config.replication_device = [
            utils.get_replication_device()]
        with utils.patch_vnxsystem:
            failover_mirror = common_adapter.build_mirror_view(
                common_adapter.config, failover=False)
        self.assertIsNotNone(failover_mirror)

    @utils.patch_extra_specs({'replication_enabled': '<is> True'})
    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_failover_host(self, common_adapter, mocked_res, mocked_input):
        device = utils.get_replication_device()
        common_adapter.config.replication_device = [device]
        vol1 = mocked_input['vol1']
        lun1 = mocked_res['lun1']
        with mock.patch.object(common_adapter, 'build_mirror_view') as fake:
            fake_mirror = utils.build_fake_mirror_view()
            fake_mirror.secondary_client.get_lun.return_value = lun1
            fake_mirror.secondary_client.get_serial.return_value = (
                device['backend_id'])
            fake.return_value = fake_mirror
            backend_id, updates, __ = common_adapter.failover_host(
                None, [vol1], device['backend_id'], [])
            fake_mirror.promote_image.assert_called_once_with(
                'mirror_' + vol1.id)
            fake_mirror.secondary_client.get_serial.assert_called_with()
            fake_mirror.secondary_client.get_lun.assert_called_with(
                name=vol1.name)
            self.assertEqual(fake_mirror.secondary_client,
                             common_adapter.client)
            self.assertEqual(device['backend_id'],
                             common_adapter.active_backend_id)
        self.assertEqual(device['backend_id'], backend_id)
        for update in updates:
            self.assertEqual(fields.ReplicationStatus.FAILED_OVER,
                             update['updates']['replication_status'])

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_failover_host_invalid_backend_id(self, common_adapter,
                                              mocked_res, mocked_input):
        common_adapter.config.replication_device = [
            utils.get_replication_device()]
        vol1 = mocked_input['vol1']
        self.assertRaises(exception.InvalidReplicationTarget,
                          common_adapter.failover_host,
                          None, [vol1], 'new_id', [])

    @utils.patch_extra_specs({'replication_enabled': '<is> True'})
    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_failover_host_failback(self, common_adapter, mocked_res,
                                    mocked_input):
        device = utils.get_replication_device()
        common_adapter.config.replication_device = [device]
        common_adapter.active_backend_id = device['backend_id']
        vol1 = mocked_input['vol1']
        lun1 = mocked_res['lun1']
        with mock.patch.object(common_adapter, 'build_mirror_view') as fake:
            fake_mirror = utils.build_fake_mirror_view()
            fake_mirror.secondary_client.get_lun.return_value = lun1
            fake_mirror.secondary_client.get_serial.return_value = (
                device['backend_id'])
            fake.return_value = fake_mirror
            backend_id, updates, __ = common_adapter.failover_host(
                None, [vol1], 'default', [])
            fake_mirror.promote_image.assert_called_once_with(
                'mirror_' + vol1.id)
            fake_mirror.secondary_client.get_serial.assert_called_with()
            fake_mirror.secondary_client.get_lun.assert_called_with(
                name=vol1.name)
            self.assertEqual(fake_mirror.secondary_client,
                             common_adapter.client)
            self.assertIsNone(common_adapter.active_backend_id)
            self.assertFalse(fake_mirror.primary_client ==
                             fake_mirror.secondary_client)
        self.assertEqual('default', backend_id)
        for update in updates:
            self.assertEqual(fields.ReplicationStatus.ENABLED,
                             update['updates']['replication_status'])

    @utils.patch_group_specs({'consistent_group_replication_enabled':
                              '<is> True'})
    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_failover_host_groups(self, common_adapter, mocked_res,
                                  mocked_input):
        device = utils.get_replication_device()
        common_adapter.config.replication_device = [device]
        common_adapter.active_backend_id = device['backend_id']
        mocked_group = mocked_input['group1']
        group1 = mock.Mock()

        group1.id = mocked_group.id
        group1.replication_status = mocked_group.replication_status
        group1.volumes = [mocked_input['vol1'], mocked_input['vol2']]
        lun1 = mocked_res['lun1']
        with mock.patch.object(common_adapter, 'build_mirror_view') as fake:
            fake_mirror = utils.build_fake_mirror_view()
            fake_mirror.secondary_client.get_lun.return_value = lun1
            fake_mirror.secondary_client.get_serial.return_value = (
                device['backend_id'])
            fake.return_value = fake_mirror
            backend_id, updates, group_update_list = (
                common_adapter.failover_host(None, [], 'default', [group1]))
            fake_mirror.promote_mirror_group.assert_called_once_with(
                group1.id.replace('-', ''))
            fake_mirror.secondary_client.get_serial.assert_called_with()
            fake_mirror.secondary_client.get_lun.assert_called_with(
                name=mocked_input['vol1'].name)
            self.assertEqual(fake_mirror.secondary_client,
                             common_adapter.client)
            self.assertEqual([{
                'group_id': group1.id,
                'updates': {'replication_status':
                            fields.ReplicationStatus.ENABLED}}],
                group_update_list)
            self.assertEqual(2, len(updates))
            self.assertIsNone(common_adapter.active_backend_id)
        self.assertEqual('default', backend_id)
        for update in updates:
            self.assertEqual(fields.ReplicationStatus.ENABLED,
                             update['updates']['replication_status'])

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_get_pool_name(self, common_adapter, mocked_res, mocked_input):
        self.assertEqual(mocked_res['lun'].pool_name,
                         common_adapter.get_pool_name(mocked_input['volume']))

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_update_migrated_volume(self, common_adapter, mocked_res,
                                    mocked_input):
        data = common_adapter.update_migrated_volume(
            None, mocked_input['volume'], mocked_input['new_volume'])
        self.assertEqual(mocked_input['new_volume'].provider_location,
                         data['provider_location'])
        self.assertEqual('False', data['metadata']['snapcopy'])

    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_update_migrated_volume_smp(self, common_adapter, mocked_res,
                                        mocked_input):
        data = common_adapter.update_migrated_volume(
            None, mocked_input['volume'], mocked_input['new_volume'])
        self.assertEqual(mocked_input['new_volume'].provider_location,
                         data['provider_location'])
        self.assertEqual('True', data['metadata']['snapcopy'])

    @res_mock.patch_common_adapter
    def test_normalize_config_queue_path(self, common_adapter,
                                         mocked_res):
        common_adapter._normalize_config()
        self.assertEqual(os.path.join(cfg.CONF.state_path,
                                      'vnx',
                                      'vnx_backend'),
                         common_adapter.queue_path)

    @res_mock.patch_common_adapter
    def test_normalize_config_naviseccli_path(self, common_adapter,
                                              mocked_res):
        old_value = common_adapter.config.naviseccli_path
        common_adapter._normalize_config()
        self.assertEqual(old_value, common_adapter.config.naviseccli_path)

    @res_mock.patch_common_adapter
    def test_normalize_config_naviseccli_path_none(self, common_adapter,
                                                   mocked_res):
        common_adapter.config.naviseccli_path = ""
        common_adapter._normalize_config()
        self.assertIsNone(common_adapter.config.naviseccli_path)

        common_adapter.config.naviseccli_path = "   "
        common_adapter._normalize_config()
        self.assertIsNone(common_adapter.config.naviseccli_path)

        common_adapter.config.naviseccli_path = None
        common_adapter._normalize_config()
        self.assertIsNone(common_adapter.config.naviseccli_path)

    @res_mock.patch_common_adapter
    def test_normalize_config_pool_names(self, common_adapter,
                                         mocked_res):
        common_adapter.config.storage_vnx_pool_names = [
            'pool_1', '  pool_2   ', '', '   ']
        common_adapter._normalize_config()
        self.assertEqual(['pool_1', 'pool_2'],
                         common_adapter.config.storage_vnx_pool_names)

    @res_mock.patch_common_adapter
    def test_normalize_config_pool_names_none(self, common_adapter,
                                              mocked_res):
        common_adapter.config.storage_vnx_pool_names = None
        common_adapter._normalize_config()
        self.assertIsNone(common_adapter.config.storage_vnx_pool_names)

    @res_mock.patch_common_adapter
    def test_normalize_config_pool_names_empty_list(self, common_adapter,
                                                    mocked_res):
        common_adapter.config.storage_vnx_pool_names = []
        self.assertRaises(exception.InvalidConfigurationValue,
                          common_adapter._normalize_config)

        common_adapter.config.storage_vnx_pool_names = ['  ', '']
        self.assertRaises(exception.InvalidConfigurationValue,
                          common_adapter._normalize_config)

    @res_mock.patch_common_adapter
    def test_normalize_config_io_port_list(self, common_adapter,
                                           mocked_res):
        common_adapter.config.io_port_list = [
            'a-0-1', '  b-1   ', '', '   ']
        common_adapter._normalize_config()
        self.assertEqual(['A-0-1', 'B-1'],
                         common_adapter.config.io_port_list)

    @res_mock.patch_common_adapter
    def test_normalize_config_io_port_list_none(self, common_adapter,
                                                mocked_res):
        common_adapter.config.io_port_list = None
        common_adapter._normalize_config()
        self.assertIsNone(common_adapter.config.io_port_list)

    @res_mock.patch_common_adapter
    def test_normalize_config_io_port_list_empty_list(self, common_adapter,
                                                      mocked_res):
        common_adapter.config.io_port_list = []
        self.assertRaises(exception.InvalidConfigurationValue,
                          common_adapter._normalize_config)

        common_adapter.config.io_port_list = ['  ', '']
        self.assertRaises(exception.InvalidConfigurationValue,
                          common_adapter._normalize_config)


class TestISCSIAdapter(test_base.TestCase):
    STORAGE_PROTOCOL = common.PROTOCOL_ISCSI

    def setUp(self):
        super(TestISCSIAdapter, self).setUp()
        vnx_utils.init_ops(self.configuration)
        self.configuration.storage_protocol = self.STORAGE_PROTOCOL

    @res_mock.patch_iscsi_adapter
    def test_validate_ports_iscsi(self, vnx_iscsi, mocked):
        all_iscsi_ports = vnx_iscsi.client.get_iscsi_targets()
        valid_ports = vnx_iscsi.validate_ports(all_iscsi_ports, ['A-0-0'])
        self.assertEqual([mocked['iscsi_port_a-0-0']], valid_ports)

    @res_mock.patch_iscsi_adapter
    def test_validate_ports_iscsi_invalid(self, vnx_iscsi, mocked):
        invalid_white_list = ['A-0-0', 'A-B-0']
        all_iscsi_ports = vnx_iscsi.client.get_iscsi_targets()
        self.assertRaisesRegex(
            exception.VolumeBackendAPIException,
            'Invalid iscsi ports %s specified for io_port_list.'
            % 'A-B-0',
            vnx_iscsi.validate_ports,
            all_iscsi_ports,
            invalid_white_list)

    @res_mock.patch_iscsi_adapter
    def test_validate_ports_iscsi_not_exist(self, vnx_iscsi, mocked):
        nonexistent_ports = ['A-0-0', 'A-6-1']
        all_iscsi_ports = vnx_iscsi.client.get_iscsi_targets()
        self.assertRaisesRegex(
            exception.VolumeBackendAPIException,
            'Invalid iscsi ports %s specified for io_port_list'
            % 'A-6-1',
            vnx_iscsi.validate_ports,
            all_iscsi_ports,
            nonexistent_ports)

    @res_mock.patch_iscsi_adapter
    def test_update_volume_stats_iscsi(self, vnx_iscsi, mocked):
        with mock.patch.object(adapter.CommonAdapter, 'update_volume_stats',
                               return_value={'storage_protocol':
                                             self.STORAGE_PROTOCOL}):
            stats = vnx_iscsi.update_volume_stats()
        self.assertEqual(self.STORAGE_PROTOCOL, stats['storage_protocol'])
        self.assertEqual('VNXISCSIDriver', stats['volume_backend_name'])

    @res_mock.patch_iscsi_adapter
    def test_build_terminate_connection_return_data_iscsi(
            self, vnx_iscsi, mocked):
        re = vnx_iscsi.build_terminate_connection_return_data(None, None)
        self.assertIsNone(re)

    @res_mock.patch_iscsi_adapter
    def test_normalize_config_iscsi_initiators(
            self, vnx_iscsi, mocked):
        vnx_iscsi.config.iscsi_initiators = (
            '{"host1":["10.0.0.1", "10.0.0.2"],"host2":["10.0.0.3"]}')
        vnx_iscsi._normalize_config()
        expected = {"host1": ["10.0.0.1", "10.0.0.2"],
                    "host2": ["10.0.0.3"]}
        self.assertEqual(expected, vnx_iscsi.config.iscsi_initiators)

        vnx_iscsi.config.iscsi_initiators = '{}'
        vnx_iscsi._normalize_config()
        expected = {}
        self.assertEqual(expected, vnx_iscsi.config.iscsi_initiators)

    @res_mock.patch_iscsi_adapter
    def test_normalize_config_iscsi_initiators_none(
            self, vnx_iscsi, mocked):
        vnx_iscsi.config.iscsi_initiators = None
        vnx_iscsi._normalize_config()
        self.assertIsNone(vnx_iscsi.config.iscsi_initiators)

    @res_mock.patch_iscsi_adapter
    def test_normalize_config_iscsi_initiators_empty_str(
            self, vnx_iscsi, mocked):
        vnx_iscsi.config.iscsi_initiators = ''
        self.assertRaises(exception.InvalidConfigurationValue,
                          vnx_iscsi._normalize_config)

        vnx_iscsi.config.iscsi_initiators = '   '
        self.assertRaises(exception.InvalidConfigurationValue,
                          vnx_iscsi._normalize_config)

    @res_mock.patch_iscsi_adapter
    def test_normalize_config_iscsi_initiators_not_dict(
            self, vnx_iscsi, mocked):
        vnx_iscsi.config.iscsi_initiators = '["a", "b"]'
        self.assertRaises(exception.InvalidConfigurationValue,
                          vnx_iscsi._normalize_config)

    @res_mock.mock_driver_input
    @res_mock.patch_iscsi_adapter
    def test_terminate_connection(self, adapter, mocked_res, mocked_input):
        cinder_volume = mocked_input['volume']
        connector = mocked_input['connector']
        adapter.remove_host_access = mock.Mock()
        adapter.update_storage_group_if_required = mock.Mock()
        adapter.build_terminate_connection_return_data = mock.Mock()
        adapter.terminate_connection_cleanup = mock.Mock()

        adapter.terminate_connection(cinder_volume, connector)
        adapter.remove_host_access.assert_called_once()
        adapter.update_storage_group_if_required.assert_called_once()
        adapter.build_terminate_connection_return_data \
            .assert_called_once()
        adapter.terminate_connection_cleanup.assert_called_once()

    @res_mock.mock_driver_input
    @res_mock.patch_iscsi_adapter
    def test_terminate_connection_force_detach(self, adapter, mocked_res,
                                               mocked_input):
        cinder_volume = mocked_input['volume']
        connector = None
        adapter.remove_host_access = mock.Mock()
        adapter.update_storage_group_if_required = mock.Mock()
        adapter.build_terminate_connection_return_data = mock.Mock()
        adapter.terminate_connection_cleanup = mock.Mock()

        adapter.terminate_connection(cinder_volume, connector)
        adapter.remove_host_access.assert_called()
        adapter.update_storage_group_if_required.assert_called()
        adapter.build_terminate_connection_return_data \
            .assert_not_called()
        adapter.terminate_connection_cleanup.assert_called()


class TestFCAdapter(test_base.TestCase):
    STORAGE_PROTOCOL = common.PROTOCOL_FC

    def setUp(self):
        super(TestFCAdapter, self).setUp()
        vnx_utils.init_ops(self.configuration)
        self.configuration.storage_protocol = self.STORAGE_PROTOCOL

    @res_mock.patch_fc_adapter
    def test_validate_ports_fc(self, vnx_fc, mocked):
        all_fc_ports = vnx_fc.client.get_fc_targets()
        valid_ports = vnx_fc.validate_ports(all_fc_ports, ['A-1'])
        self.assertEqual([mocked['fc_port_a-1']], valid_ports)

    @res_mock.patch_fc_adapter
    def test_validate_ports_fc_invalid(self, vnx_fc, mocked):
        invalid_white_list = ['A-1', 'A-B']
        all_fc_ports = vnx_fc.client.get_fc_targets()
        self.assertRaisesRegex(
            exception.VolumeBackendAPIException,
            'Invalid fc ports %s specified for io_port_list.'
            % 'A-B',
            vnx_fc.validate_ports,
            all_fc_ports,
            invalid_white_list)

    @res_mock.patch_fc_adapter
    def test_validate_ports_fc_not_exist(self, vnx_fc, mocked):
        nonexistent_ports = ['A-1', 'A-6']
        all_fc_ports = vnx_fc.client.get_fc_targets()
        self.assertRaisesRegex(
            exception.VolumeBackendAPIException,
            'Invalid fc ports %s specified for io_port_list'
            % 'A-6',
            vnx_fc.validate_ports,
            all_fc_ports,
            nonexistent_ports)

    @res_mock.patch_fc_adapter
    def test_update_volume_stats(self, vnx_fc, mocked):
        with mock.patch.object(adapter.CommonAdapter, 'get_pool_stats'):
            stats = vnx_fc.update_volume_stats()
        self.assertEqual(self.STORAGE_PROTOCOL, stats['storage_protocol'])
        self.assertEqual('VNXFCDriver', stats['volume_backend_name'])

    @mock.patch.object(vnx_utils, 'convert_to_tgt_list_and_itor_tgt_map')
    @res_mock.patch_fc_adapter
    def test_build_terminate_connection_return_data_auto_zone(
            self, vnx_fc, mocked, converter):
        vnx_fc.lookup_service = mock.Mock()
        get_mapping = vnx_fc.lookup_service.get_device_mapping_from_network

        itor_tgt_map = {
            'wwn1': ['wwnt1', 'wwnt2', 'wwnt3'],
            'wwn2': ['wwnt1', 'wwnt2']
        }
        converter.return_value = ([], itor_tgt_map)
        host = common.Host('fake_host',
                           ['fake_hba1'],
                           wwpns=['wwn1', 'wwn2'])
        sg = mocked['sg']
        re = vnx_fc.build_terminate_connection_return_data(host, sg)
        get_mapping.assert_called_once_with(
            ['wwn1', 'wwn2'], ['5006016636E01CA1'])
        self.assertEqual(itor_tgt_map,
                         re['data']['initiator_target_map'])

    @res_mock.patch_fc_adapter
    def test_build_terminate_connection_return_data_sg_absent(
            self, vnx_fc, mocked):
        sg = mocked['sg']
        re = vnx_fc.build_terminate_connection_return_data(None, sg)
        self.assertEqual('fibre_channel', re['driver_volume_type'])
        self.assertEqual({}, re['data'])

    @res_mock.patch_fc_adapter
    def test_build_terminate_connection_return_data_without_autozone(
            self, vnx_fc, mocked):
        self.lookup_service = None
        re = vnx_fc.build_terminate_connection_return_data(None, None)
        self.assertEqual('fibre_channel', re['driver_volume_type'])
        self.assertEqual({}, re['data'])

    @res_mock.patch_fc_adapter
    def test_get_tgt_list_and_initiator_tgt_map_allow_port_only(
            self, vnx_fc, mocked):
        sg = mocked['sg']
        host = common.Host('fake_host',
                           ['fake_hba1'],
                           wwpns=['wwn1', 'wwn2'])
        mapping = {
            'san_1': {'initiator_port_wwn_list': ['wwn1'],
                      'target_port_wwn_list': ['5006016636E01CB2']}}
        vnx_fc.lookup_service = mock.Mock()
        vnx_fc.lookup_service.get_device_mapping_from_network = mock.Mock(
            return_value=mapping)
        get_mapping = vnx_fc.lookup_service.get_device_mapping_from_network
        vnx_fc.allowed_ports = mocked['adapter'].allowed_ports
        targets, tgt_map = vnx_fc._get_tgt_list_and_initiator_tgt_map(
            sg, host, True)
        self.assertEqual(['5006016636E01CB2'], targets)
        self.assertEqual({'wwn1': ['5006016636E01CB2']}, tgt_map)
        get_mapping.assert_called_once_with(
            ['wwn1', 'wwn2'], ['5006016636E01CB2'])

    @res_mock.mock_driver_input
    @res_mock.patch_iscsi_adapter
    def test_terminate_connection(self, adapter, mocked_res, mocked_input):
        cinder_volume = mocked_input['volume']
        connector = mocked_input['connector']
        adapter.remove_host_access = mock.Mock()
        adapter.update_storage_group_if_required = mock.Mock()
        adapter.build_terminate_connection_return_data = mock.Mock()
        adapter.terminate_connection_cleanup = mock.Mock()

        adapter.terminate_connection(cinder_volume, connector)
        adapter.remove_host_access.assert_called_once()
        adapter.update_storage_group_if_required.assert_called_once()
        adapter.build_terminate_connection_return_data \
            .assert_called_once()
        adapter.terminate_connection_cleanup.assert_called_once()

    @res_mock.mock_driver_input
    @res_mock.patch_iscsi_adapter
    def test_terminate_connection_force_detach(self, adapter, mocked_res,
                                               mocked_input):
        cinder_volume = mocked_input['volume']
        connector = None
        adapter.remove_host_access = mock.Mock()
        adapter.update_storage_group_if_required = mock.Mock()
        adapter.build_terminate_connection_return_data = mock.Mock()
        adapter.terminate_connection_cleanup = mock.Mock()

        adapter.terminate_connection(cinder_volume, connector)
        adapter.remove_host_access.assert_called()
        adapter.update_storage_group_if_required.assert_called()
        adapter.build_terminate_connection_return_data \
            .assert_not_called()
        adapter.terminate_connection_cleanup.assert_called()
