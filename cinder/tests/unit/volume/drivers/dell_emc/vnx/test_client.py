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
import unittest

from cinder import exception
from cinder.tests.unit.volume.drivers.dell_emc.vnx import fake_exception \
    as storops_ex
from cinder.tests.unit.volume.drivers.dell_emc.vnx import fake_storops \
    as storops
from cinder.tests.unit.volume.drivers.dell_emc.vnx import res_mock
from cinder.tests.unit.volume.drivers.dell_emc.vnx import test_base
from cinder.tests.unit.volume.drivers.dell_emc.vnx import utils
from cinder.volume.drivers.dell_emc.vnx import client as vnx_client
from cinder.volume.drivers.dell_emc.vnx import common as vnx_common


class TestCondition(test_base.TestCase):
    @res_mock.patch_client
    def test_is_lun_io_ready_false(self, client, mocked):
        r = vnx_client.Condition.is_lun_io_ready(mocked['lun'])
        self.assertFalse(r)

    @res_mock.patch_client
    def test_is_lun_io_ready_true(self, client, mocked):
        r = vnx_client.Condition.is_lun_io_ready(mocked['lun'])
        self.assertTrue(r)

    @res_mock.patch_client
    def test_is_lun_io_ready_exception(self, client, mocked):
        self.assertRaises(exception.VolumeBackendAPIException,
                          vnx_client.Condition.is_lun_io_ready,
                          mocked['lun'])


class TestClient(test_base.TestCase):

    @res_mock.patch_client
    def test_create_lun(self, client, mocked):
        client.create_lun(pool='pool1', name='test', size=1, provision=None,
                          tier=None, cg_id=None, ignore_thresholds=False)
        client.vnx.get_pool.assert_called_once_with(name='pool1')
        pool = client.vnx.get_pool(name='pool1')
        pool.create_lun.assert_called_with(lun_name='test',
                                           size_gb=1,
                                           provision=None,
                                           tier=None,
                                           ignore_thresholds=False)

    @res_mock.patch_client
    def test_create_lun_error(self, client, mocked):
        self.assertRaises(storops_ex.VNXCreateLunError,
                          client.create_lun,
                          pool='pool1',
                          name='test',
                          size=1,
                          provision=None,
                          tier=None,
                          cg_id=None,
                          ignore_thresholds=False)
        client.vnx.get_pool.assert_called_once_with(name='pool1')

    @res_mock.patch_client
    def test_create_lun_already_existed(self, client, mocked):
        client.create_lun(pool='pool1', name='lun3', size=1, provision=None,
                          tier=None, cg_id=None, ignore_thresholds=False)
        client.vnx.get_lun.assert_called_once_with(name='lun3')

    @res_mock.patch_client
    def test_create_lun_in_cg(self, client, mocked):
        client.create_lun(
            pool='pool1', name='test', size=1, provision=None,
            tier=None, cg_id='cg1', ignore_thresholds=False)

    @res_mock.patch_client
    def test_create_lun_compression(self, client, mocked):
        client.create_lun(pool='pool1', name='lun2', size=1,
                          provision=storops.VNXProvisionEnum.COMPRESSED,
                          tier=None, cg_id=None,
                          ignore_thresholds=False)

    @res_mock.patch_client
    def test_migrate_lun(self, client, mocked):
        client.migrate_lun(src_id=1,
                           dst_id=2)
        lun = client.vnx.get_lun()
        lun.migrate.assert_called_with(2, storops.VNXMigrationRate.HIGH)

    @unittest.skip("Skip until bug #1578986 is fixed")
    @utils.patch_sleep
    @res_mock.patch_client
    def test_migrate_lun_with_retry(self, client, mocked, mock_sleep):
        lun = client.vnx.get_lun()
        self.assertRaises(storops_ex.VNXTargetNotReadyError,
                          client.migrate_lun,
                          src_id=4,
                          dst_id=5)
        lun.migrate.assert_called_with(5, storops.VNXMigrationRate.HIGH)

    @res_mock.patch_client
    def test_session_finished_faulted(self, client, mocked):
        lun = client.vnx.get_lun()
        r = client.session_finished(lun)
        self.assertTrue(r)

    @res_mock.patch_client
    def test_session_finished_migrating(self, client, mocked):
        lun = client.vnx.get_lun()
        r = client.session_finished(lun)
        self.assertFalse(r)

    @res_mock.patch_client
    def test_session_finished_not_existed(self, client, mocked):
        lun = client.vnx.get_lun()
        r = client.session_finished(lun)
        self.assertTrue(r)

    @res_mock.patch_client
    def test_migrate_lun_error(self, client, mocked):
        lun = client.vnx.get_lun()
        self.assertRaises(storops_ex.VNXMigrationError,
                          client.migrate_lun,
                          src_id=4,
                          dst_id=5)
        lun.migrate.assert_called_with(5, storops.VNXMigrationRate.HIGH)

    @res_mock.patch_client
    def test_verify_migration(self, client, mocked):
        r = client.verify_migration(1, 2, 'test_wwn')
        self.assertTrue(r)

    @res_mock.patch_client
    def test_verify_migration_false(self, client, mocked):
        r = client.verify_migration(1, 2, 'fake_wwn')
        self.assertFalse(r)

    @res_mock.patch_client
    def test_cleanup_migration(self, client, mocked):
        client.cleanup_migration(1, 2)

    @res_mock.patch_client
    def test_cleanup_migration_not_migrating(self, client, mocked):
        client.cleanup_migration(1, 2)

    @res_mock.patch_client
    def test_cleanup_migration_cancel_failed(self, client, mocked):
        client.cleanup_migration(1, 2)

    @res_mock.patch_client
    def test_get_lun_by_name(self, client, mocked):
        lun = client.get_lun(name='lun_name_test_get_lun_by_name')
        self.assertEqual(888, lun.lun_id)

    @res_mock.patch_client
    def test_delete_lun(self, client, mocked):
        client.delete_lun(mocked['lun'].name)

    @res_mock.patch_client
    def test_delete_smp(self, client, mocked):
        client.delete_lun(mocked['lun'].name, snap_copy='snap-as-vol')

    @res_mock.patch_client
    def test_delete_lun_not_exist(self, client, mocked):
        client.delete_lun(mocked['lun'].name)

    @res_mock.patch_client
    def test_delete_lun_exception(self, client, mocked):
        self.assertRaisesRegex(storops_ex.VNXDeleteLunError,
                               'General lun delete error.',
                               client.delete_lun, mocked['lun'].name)

    @res_mock.patch_client
    def test_cleanup_async_lun(self, client, mocked):
        client.cleanup_async_lun(
            mocked['lun'].name,
            force=True)

    @res_mock.patch_client
    def test_enable_compression(self, client, mocked):
        lun_obj = mocked['lun']
        client.enable_compression(lun_obj)
        lun_obj.enable_compression.assert_called_with(ignore_thresholds=True)

    @res_mock.patch_client
    def test_enable_compression_on_compressed_lun(self, client, mocked):
        lun_obj = mocked['lun']
        client.enable_compression(lun_obj)

    @res_mock.patch_client
    def test_get_vnx_enabler_status(self, client, mocked):
        re = client.get_vnx_enabler_status()
        self.assertTrue(re.dedup_enabled)
        self.assertFalse(re.compression_enabled)
        self.assertTrue(re.thin_enabled)
        self.assertFalse(re.fast_enabled)
        self.assertTrue(re.snap_enabled)

    @res_mock.patch_client
    def test_lun_has_snapshot_true(self, client, mocked):
        re = client.lun_has_snapshot(mocked['lun'])
        self.assertTrue(re)

    @res_mock.patch_client
    def test_lun_has_snapshot_false(self, client, mocked):
        re = client.lun_has_snapshot(mocked['lun'])
        self.assertFalse(re)

    @res_mock.patch_client
    def test_create_cg(self, client, mocked):
        cg = client.create_consistency_group('cg_name')
        self.assertIsNotNone(cg)

    @res_mock.patch_client
    def test_create_cg_already_existed(self, client, mocked):
        cg = client.create_consistency_group('cg_name_already_existed')
        self.assertIsNotNone(cg)

    @res_mock.patch_client
    def test_delete_cg(self, client, mocked):
        client.delete_consistency_group('deleted_name')

    @res_mock.patch_client
    def test_delete_cg_not_existed(self, client, mocked):
        client.delete_consistency_group('not_existed')

    @res_mock.patch_client
    def test_expand_lun(self, client, _ignore):
        client.expand_lun('lun', 10, poll=True)

    @res_mock.patch_client
    def test_expand_lun_not_poll(self, client, _ignore):
        client.expand_lun('lun', 10, poll=False)

    @res_mock.patch_client
    def test_expand_lun_already_expanded(self, client, _ignore):
        client.expand_lun('lun', 10)

    @res_mock.patch_client
    def test_expand_lun_not_ops_ready(self, client, _ignore):
        self.assertRaises(storops_ex.VNXLunPreparingError,
                          client.expand_lun, 'lun', 10)
        lun = client.vnx.get_lun()
        lun.expand.assert_called_once_with(10, ignore_thresholds=True)
        # Called twice
        lun.expand.assert_called_once_with(10, ignore_thresholds=True)

    @res_mock.patch_client
    def test_create_snapshot(self, client, _ignore):
        client.create_snapshot('lun_test_create_snapshot',
                               'snap_test_create_snapshot')

        lun = client.vnx.get_lun()
        lun.create_snap.assert_called_once_with('snap_test_create_snapshot',
                                                allow_rw=True,
                                                auto_delete=False,
                                                keep_for=None)

    @res_mock.patch_client
    def test_create_snapshot_snap_name_exist_error(self, client, _ignore):
        client.create_snapshot('lun_name', 'snapshot_name')

    @res_mock.patch_client
    def test_delete_snapshot(self, client, _ignore):
        client.delete_snapshot('snapshot_name')

    @res_mock.patch_client
    def test_delete_snapshot_delete_attached_error(self, client, _ignore):
        self.assertRaises(storops_ex.VNXDeleteAttachedSnapError,
                          client.delete_snapshot, 'snapshot_name')

    @res_mock.patch_client
    def test_copy_snapshot(self, client, mocked):
        client.copy_snapshot('old_name', 'new_name')

    @res_mock.patch_client
    def test_create_mount_point(self, client, mocked):
        client.create_mount_point('lun_name', 'smp_name')

    @res_mock.patch_client
    def test_attach_mount_point(self, client, mocked):
        client.attach_snapshot('smp_name', 'snap_name')

    @res_mock.patch_client
    def test_detach_mount_point(self, client, mocked):
        client.detach_snapshot('smp_name')

    @res_mock.patch_client
    def test_modify_snapshot(self, client, mocked):
        client.modify_snapshot('snap_name', True, True)

    @res_mock.patch_client
    def test_restore_snapshot(self, client, mocked):
        client.restore_snapshot('lun-id', 'snap_name')

    @res_mock.patch_client
    def test_create_cg_snapshot(self, client, mocked):
        snap = client.create_cg_snapshot('cg_snap_name', 'cg_name')
        self.assertIsNotNone(snap)

    @res_mock.patch_client
    def test_create_cg_snapshot_already_existed(self, client, mocked):
        snap = client.create_cg_snapshot('cg_snap_name', 'cg_name')
        self.assertIsNotNone(snap)

    @res_mock.patch_client
    def test_delete_cg_snapshot(self, client, mocked):
        client.delete_cg_snapshot(cg_snap_name='test_snap')

    @res_mock.patch_client
    def test_create_sg(self, client, mocked):
        client.create_storage_group('sg_name')

    @res_mock.patch_client
    def test_create_sg_name_in_use(self, client, mocked):
        client.create_storage_group('sg_name')
        self.assertIsNotNone(client.sg_cache['sg_name'])
        self.assertTrue(client.sg_cache['sg_name'].existed)

    @res_mock.patch_client
    def test_get_storage_group(self, client, mocked):
        sg = client.get_storage_group('sg_name')
        self.assertEqual('sg_name', sg.name)

    @res_mock.patch_client
    def test_register_initiator(self, client, mocked):
        host = vnx_common.Host('host_name', ['host_initiator'], 'host_ip')
        client.register_initiator(mocked['sg'], host,
                                  {'host_initiator': 'port_1'})

    @res_mock.patch_client
    def test_register_initiator_exception(self, client, mocked):
        host = vnx_common.Host('host_name', ['host_initiator'], 'host_ip')
        client.register_initiator(mocked['sg'], host,
                                  {'host_initiator': 'port_1'})

    @res_mock.patch_client
    def test_ping_node(self, client, mocked):
        self.assertTrue(client.ping_node(mocked['iscsi_port'], 'ip'))

    @res_mock.patch_client
    def test_ping_node_fail(self, client, mocked):
        self.assertFalse(client.ping_node(mocked['iscsi_port'], 'ip'))

    @res_mock.patch_client
    def test_add_lun_to_sg(self, client, mocked):
        lun = 'not_care'
        self.assertEqual(1, client.add_lun_to_sg(mocked['sg'], lun, 3))

    @res_mock.patch_client
    def test_add_lun_to_sg_alu_already_attached(self, client, mocked):
        lun = 'not_care'
        self.assertEqual(1, client.add_lun_to_sg(mocked['sg'], lun, 3))

    @res_mock.patch_client
    def test_add_lun_to_sg_alu_in_use(self, client, mocked):
        self.assertRaisesRegex(storops_ex.VNXNoHluAvailableError,
                               'No HLU available.',
                               client.add_lun_to_sg,
                               mocked['sg'],
                               mocked['lun'],
                               3)

    @res_mock.patch_client
    def test_update_consistencygroup_no_lun_in_cg(self, client, mocked):
        lun_1 = mocked['lun_1']
        lun_2 = mocked['lun_2']

        def _get_lun(lun_id):
            return [x for x in (lun_1, lun_2) if x.lun_id == lun_id][0]

        client.get_lun = _get_lun
        cg = mocked['cg']

        client.update_consistencygroup(cg, [lun_1.lun_id, lun_2.lun_id], [])
        cg.replace_member.assert_called_once_with(lun_1, lun_2)

    @res_mock.patch_client
    def test_update_consistencygroup_lun_in_cg(self, client, mocked):
        lun_1 = mocked['lun_1']
        lun_2 = mocked['lun_2']

        def _get_lun(lun_id):
            return [x for x in (lun_1, lun_2) if x.lun_id == lun_id][0]

        client.get_lun = _get_lun
        cg = mocked['cg']

        client.update_consistencygroup(cg, [lun_2.lun_id], [lun_1.lun_id])
        cg.replace_member.assert_called_once_with(lun_2)

    @res_mock.patch_client
    def test_update_consistencygroup_remove_all(self, client, mocked):
        lun_1 = mocked['lun_1']

        def _get_lun(lun_id):
            return [x for x in (lun_1,) if x.lun_id == lun_id][0]

        client.get_lun = _get_lun
        cg = mocked['cg']

        client.update_consistencygroup(cg, [], [lun_1.lun_id])
        cg.delete_member.assert_called_once_with(lun_1)

    @res_mock.patch_client
    def test_get_available_ip(self, client, mocked):
        ip = client.get_available_ip()
        self.assertEqual('192.168.1.5', ip)

    @res_mock.patch_client
    def test_create_mirror(self, client, mocked):
        mv = client.create_mirror('test_mirror_name', 11)
        self.assertIsNotNone(mv)

    @res_mock.patch_client
    def test_create_mirror_already_created(self, client, mocked):
        mv = client.create_mirror('error_mirror', 12)
        self.assertIsNotNone(mv)

    @res_mock.patch_client
    def test_delete_mirror(self, client, mocked):
        client.delete_mirror('mirror_name')

    @res_mock.patch_client
    def test_delete_mirror_already_deleted(self, client, mocked):
        client.delete_mirror('mirror_name_deleted')

    @res_mock.patch_client
    def test_add_image(self, client, mocked):
        client.add_image('mirror_namex', '192.168.1.11', 31)

    @res_mock.patch_client
    def test_remove_image(self, client, mocked):
        client.remove_image('mirror_remove')

    @res_mock.patch_client
    def test_fracture_image(self, client, mocked):
        client.fracture_image('mirror_fracture')

    @res_mock.patch_client
    def test_sync_image(self, client, mocked):
        client.sync_image('mirror_sync')

    @res_mock.patch_client
    def test_promote_image(self, client, mocked):
        client.promote_image('mirror_promote')

    @res_mock.patch_client
    def test_create_mirror_group(self, client, mocked):
        group_name = 'test_mg'
        mg = client.create_mirror_group(group_name)
        self.assertIsNotNone(mg)

    @res_mock.patch_client
    def test_create_mirror_group_name_in_use(self, client, mocked):
        group_name = 'test_mg_name_in_use'
        mg = client.create_mirror_group(group_name)
        self.assertIsNotNone(mg)

    @res_mock.patch_client
    def test_delete_mirror_group(self, client, mocked):
        group_name = 'delete_name'
        client.delete_mirror_group(group_name)

    @res_mock.patch_client
    def test_delete_mirror_group_not_found(self, client, mocked):
        group_name = 'group_not_found'
        client.delete_mirror_group(group_name)

    @res_mock.patch_client
    def test_add_mirror(self, client, mocked):
        group_name = 'group_add_mirror'
        mirror_name = 'mirror_name'
        client.add_mirror(group_name, mirror_name)

    @res_mock.patch_client
    def test_add_mirror_already_added(self, client, mocked):
        group_name = 'group_already_added'
        mirror_name = 'mirror_name'
        client.add_mirror(group_name, mirror_name)

    @res_mock.patch_client
    def test_remove_mirror(self, client, mocked):
        group_name = 'group_mirror'
        mirror_name = 'mirror_name'
        client.remove_mirror(group_name, mirror_name)

    @res_mock.patch_client
    def test_remove_mirror_not_member(self, client, mocked):
        group_name = 'group_mirror'
        mirror_name = 'mirror_name_not_member'
        client.remove_mirror(group_name, mirror_name)

    @res_mock.patch_client
    def test_promote_mirror_group(self, client, mocked):
        group_name = 'group_promote'
        client.promote_mirror_group(group_name)

    @res_mock.patch_client
    def test_promote_mirror_group_already_promoted(self, client, mocked):
        group_name = 'group_promote'
        client.promote_mirror_group(group_name)

    @res_mock.patch_client
    def test_sync_mirror_group(self, client, mocked):
        group_name = 'group_sync'
        client.sync_mirror_group(group_name)

    @res_mock.patch_client
    def test_fracture_mirror_group(self, client, mocked):
        group_name = 'group_fracture'
        client.fracture_mirror_group(group_name)

    @res_mock.mock_driver_input
    @res_mock.patch_client
    def test_get_lun_id(self, client, mocked, cinder_input):
        lun_id = client.get_lun_id(cinder_input['volume'])
        self.assertEqual(1, lun_id)

    @res_mock.mock_driver_input
    @res_mock.patch_client
    def test_get_lun_id_without_provider_location(self, client, mocked,
                                                  cinder_input):
        lun_id = client.get_lun_id(cinder_input['volume'])
        self.assertIsInstance(lun_id, int)
        self.assertEqual(mocked['lun'].lun_id, lun_id)

    @res_mock.patch_client
    def test_get_ioclass(self, client, mocked):
        qos_specs = {'id': 'qos', vnx_common.QOS_MAX_IOPS: 10,
                     vnx_common.QOS_MAX_BWS: 100}
        ioclasses = client.get_ioclass(qos_specs)
        self.assertEqual(2, len(ioclasses))

    @res_mock.patch_client
    def test_create_ioclass_iops(self, client, mocked):
        ioclass = client.create_ioclass_iops('test', 1000)
        self.assertIsNotNone(ioclass)

    @res_mock.patch_client
    def test_create_ioclass_bws(self, client, mocked):
        ioclass = client.create_ioclass_bws('test', 100)
        self.assertIsNotNone(ioclass)

    @res_mock.patch_client
    def test_create_policy(self, client, mocked):
        policy = client.create_policy('policy_name')
        self.assertIsNotNone(policy)

    @res_mock.patch_client
    def test_get_running_policy(self, client, mocked):
        policy, is_new = client.get_running_policy()
        self.assertIn(policy.state, ['Running', 'Measuring'])
        self.assertFalse(is_new)

    @res_mock.patch_client
    def test_add_lun_to_ioclass(self, client, mocked):
        client.add_lun_to_ioclass('test_ioclass', 1)

    @res_mock.patch_client
    def test_set_max_luns_per_sg(self, client, mocked):
        with utils.patch_vnxstoragegroup as patch_sg:
            client.set_max_luns_per_sg(300)
            patch_sg.set_max_luns_per_sg.assert_called_with(300)
