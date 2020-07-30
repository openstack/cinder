# Copyright (c) 2020 Dell Inc. or its subsidiaries.
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

from cinder import exception
from cinder.tests.unit import test
from cinder.tests.unit import utils as test_utils
from cinder.tests.unit.volume.drivers.dell_emc.powermax import (
    powermax_data as tpd)
from cinder.tests.unit.volume.drivers.dell_emc.powermax import (
    powermax_fake_objects as tpfo)
from cinder.volume.drivers.dell_emc.powermax import iscsi
from cinder.volume.drivers.dell_emc.powermax import provision
from cinder.volume.drivers.dell_emc.powermax import rest
from cinder.volume import volume_utils


class PowerMaxProvisionTest(test.TestCase):
    def setUp(self):
        self.data = tpd.PowerMaxData()
        super(PowerMaxProvisionTest, self).setUp()
        volume_utils.get_max_over_subscription_ratio = mock.Mock()
        configuration = tpfo.FakeConfiguration(
            None, 'ProvisionTests', 1, 1, san_ip='1.1.1.1', san_login='smc',
            powermax_array=self.data.array, powermax_srp='SRP_1',
            san_password='smc', san_api_port=8443,
            powermax_port_groups=[self.data.port_group_name_i])
        rest.PowerMaxRest._establish_rest_session = mock.Mock(
            return_value=tpfo.FakeRequestsSession())
        driver = iscsi.PowerMaxISCSIDriver(configuration=configuration)
        self.driver = driver
        self.common = self.driver.common
        self.provision = self.common.provision
        self.utils = self.common.utils
        self.rest = self.common.rest

    @mock.patch.object(rest.PowerMaxRest, 'create_storage_group',
                       return_value=tpd.PowerMaxData.storagegroup_name_f)
    @mock.patch.object(rest.PowerMaxRest, 'get_storage_group',
                       side_effect=[
                           tpd.PowerMaxData.storagegroup_name_f, None])
    def test_create_storage_group(self, mock_get_sg, mock_create):
        array = self.data.array
        storagegroup_name = self.data.storagegroup_name_f
        srp = self.data.srp
        slo = self.data.slo
        workload = self.data.workload
        extra_specs = self.data.extra_specs
        for x in range(0, 2):
            storagegroup = self.provision.create_storage_group(
                array, storagegroup_name, srp, slo, workload, extra_specs)
            self.assertEqual(storagegroup_name, storagegroup)
        mock_create.assert_called_once()

    def test_create_volume_from_sg(self):
        array = self.data.array
        storagegroup_name = self.data.storagegroup_name_f
        volume_id = self.data.test_volume.id
        volume_name = self.utils.get_volume_element_name(volume_id)
        volume_size = self.data.test_volume.size
        extra_specs = self.data.extra_specs
        ref_dict = self.data.provider_location
        volume_dict = self.provision.create_volume_from_sg(
            array, volume_name, storagegroup_name, volume_size, extra_specs)
        self.assertEqual(ref_dict, volume_dict)

    @mock.patch.object(rest.PowerMaxRest, 'create_volume_from_sg')
    def test_create_volume_from_sg_with_rep_info(self, mck_create):
        array = self.data.array
        storagegroup_name = self.data.storagegroup_name_f
        volume_id = self.data.test_volume.id
        volume_name = self.utils.get_volume_element_name(volume_id)
        volume_size = self.data.test_volume.size
        extra_specs = self.data.extra_specs
        rep_info_dict = self.data.rep_info_dict

        self.provision.create_volume_from_sg(
            array, volume_name, storagegroup_name, volume_size, extra_specs,
            rep_info=rep_info_dict)
        mck_create.assert_called_once_with(
            array, volume_name, storagegroup_name, volume_size, extra_specs,
            rep_info_dict)

    def test_delete_volume_from_srp(self):
        array = self.data.array
        device_id = self.data.device_id
        volume_name = self.data.volume_details[0]['volume_identifier']
        with mock.patch.object(self.provision.rest, 'delete_volume'):
            self.provision.delete_volume_from_srp(
                array, device_id, volume_name)
            self.provision.rest.delete_volume.assert_called_once_with(
                array, device_id)

    def test_create_volume_snap_vx(self):
        array = self.data.array
        source_device_id = self.data.device_id
        snap_name = self.data.snap_location['snap_name']
        extra_specs = self.data.extra_specs
        ttl = 0
        with mock.patch.object(self.provision.rest, 'create_volume_snap'):
            self.provision.create_volume_snapvx(
                array, source_device_id, snap_name, extra_specs)
            self.provision.rest.create_volume_snap.assert_called_once_with(
                array, snap_name, source_device_id, extra_specs, ttl)

    def test_create_volume_replica_create_snap_true(self):
        array = self.data.array
        source_device_id = self.data.device_id
        target_device_id = self.data.device_id2
        snap_name = self.data.snap_location['snap_name']
        extra_specs = self.data.extra_specs
        # TTL of 1 hours
        ttl = 1
        with mock.patch.object(
                self.provision, 'create_volume_snapvx') as mock_create_snapvx:
            with mock.patch.object(
                    self.provision.rest, 'modify_volume_snap') as mock_modify:
                self.provision.create_volume_replica(
                    array, source_device_id, target_device_id,
                    snap_name, extra_specs, create_snap=True)
                mock_modify.assert_called_once_with(
                    array, source_device_id, target_device_id, snap_name,
                    extra_specs, link=True, copy=False)
                mock_create_snapvx.assert_called_once_with(
                    array, source_device_id, snap_name, extra_specs, ttl=ttl)

    def test_create_volume_replica_create_snap_false(self):
        array = self.data.array
        source_device_id = self.data.device_id
        target_device_id = self.data.device_id2
        snap_name = self.data.snap_location['snap_name']
        extra_specs = self.data.extra_specs
        with mock.patch.object(
                self.provision, 'create_volume_snapvx') as mock_create_snapvx:
            with mock.patch.object(
                    self.provision.rest, 'modify_volume_snap') as mock_modify:
                self.provision.create_volume_replica(
                    array, source_device_id, target_device_id,
                    snap_name, extra_specs, create_snap=False, copy_mode=True)
                mock_modify.assert_called_once_with(
                    array, source_device_id, target_device_id, snap_name,
                    extra_specs, link=True, copy=True)
                mock_create_snapvx.assert_not_called()

    def test_unlink_snapvx_tgt_volume(self):
        array = self.data.array
        source_device_id = self.data.device_id
        target_device_id = self.data.device_id2
        snap_name = self.data.snap_location['snap_name']
        extra_specs = self.data.extra_specs

        with mock.patch.object(
                self.provision, '_unlink_volume') as mock_unlink:
            self.provision.unlink_snapvx_tgt_volume(
                array, target_device_id, source_device_id, snap_name,
                extra_specs, self.data.snap_id, loop=True)
            mock_unlink.assert_called_once_with(
                array, source_device_id, target_device_id,
                snap_name, extra_specs, snap_id=self.data.snap_id,
                list_volume_pairs=None, loop=True)

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new=test_utils.ZeroIntervalLoopingCall)
    def test_unlink_volume(self):
        with mock.patch.object(self.rest, 'modify_volume_snap') as mock_mod:
            self.provision._unlink_volume(
                self.data.array, self.data.device_id, self.data.device_id2,
                self.data.snap_location['snap_name'], self.data.extra_specs,
                snap_id=self.data.snap_id)
            mock_mod.assert_called_once_with(
                self.data.array, self.data.device_id, self.data.device_id2,
                self.data.snap_location['snap_name'], self.data.extra_specs,
                snap_id=self.data.snap_id, list_volume_pairs=None, unlink=True)

            mock_mod.reset_mock()
            self.provision._unlink_volume(
                self.data.array, self.data.device_id, self.data.device_id2,
                self.data.snap_location['snap_name'], self.data.extra_specs,
                snap_id=self.data.snap_id, loop=False)
            mock_mod.assert_called_once_with(
                self.data.array, self.data.device_id, self.data.device_id2,
                self.data.snap_location['snap_name'], self.data.extra_specs,
                snap_id=self.data.snap_id, list_volume_pairs=None, unlink=True)

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new=test_utils.ZeroIntervalLoopingCall)
    def test_unlink_volume_exception(self):
        with mock.patch.object(
                self.rest, 'modify_volume_snap',
                side_effect=[exception.VolumeBackendAPIException(data=''), '']
        ) as mock_mod:
            self.provision._unlink_volume(
                self.data.array, self.data.device_id, self.data.device_id2,
                self.data.snap_location['snap_name'], self.data.extra_specs,
                self.data.snap_id)
            self.assertEqual(2, mock_mod.call_count)

    def test_delete_volume_snap(self):
        array = self.data.array
        source_device_id = self.data.device_id
        snap_name = self.data.snap_location['snap_name']
        with mock.patch.object(self.provision.rest, 'delete_volume_snap'):
            self.provision.delete_volume_snap(
                array, snap_name, source_device_id, snap_id=self.data.snap_id)
            self.provision.rest.delete_volume_snap.assert_called_once_with(
                array, snap_name, source_device_id, snap_id=self.data.snap_id,
                restored=False)

    def test_delete_volume_snap_restore(self):
        array = self.data.array
        source_device_id = self.data.device_id
        snap_name = self.data.snap_location['snap_name']
        restored = True
        with mock.patch.object(self.provision.rest, 'delete_volume_snap'):
            self.provision.delete_volume_snap(
                array, snap_name, source_device_id, snap_id=self.data.snap_id,
                restored=restored)
            self.provision.rest.delete_volume_snap.assert_called_once_with(
                array, snap_name, source_device_id, snap_id=self.data.snap_id,
                restored=True)

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new=test_utils.ZeroIntervalLoopingCall)
    def test_restore_complete(self):
        array = self.data.array
        source_device_id = self.data.device_id
        snap_name = self.data.snap_location['snap_name']
        snap_id = self.data.snap_id
        extra_specs = self.data.extra_specs
        with mock.patch.object(
                self.provision, '_is_restore_complete',
                return_value=True):
            isrestored = self.provision.is_restore_complete(
                array, source_device_id, snap_name, snap_id, extra_specs)
            self.assertTrue(isrestored)
        with mock.patch.object(
                self.provision, '_is_restore_complete',
                side_effect=exception.CinderException):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.provision.is_restore_complete,
                              array, source_device_id, snap_name, snap_id,
                              extra_specs)

    def test_is_restore_complete(self):
        array = self.data.array
        source_device_id = self.data.device_id
        snap_name = self.data.snap_location['snap_name']
        snap_id = self.data.snap_id
        snap_details = {
            'linkedDevices':
                [{'targetDevice': source_device_id, 'state': 'Restored'}]}
        with mock.patch.object(self.provision.rest,
                               'get_volume_snap', return_value=snap_details):
            isrestored = self.provision._is_restore_complete(
                array, source_device_id, snap_name, snap_id)
            self.assertTrue(isrestored)
        snap_details['linkedDevices'][0]['state'] = 'Restoring'
        with mock.patch.object(self.provision.rest,
                               'get_volume_snap', return_value=snap_details):
            isrestored = self.provision._is_restore_complete(
                array, source_device_id, snap_name, snap_id)
            self.assertFalse(isrestored)

    def test_revert_volume_snapshot(self):
        array = self.data.array
        source_device_id = self.data.device_id
        snap_name = self.data.snap_location['snap_name']
        extra_specs = self.data.extra_specs
        snap_id = self.data.snap_id
        with mock.patch.object(
                self.provision.rest, 'modify_volume_snap', return_value=None):
            self.provision.revert_volume_snapshot(
                array, source_device_id, snap_name, snap_id, extra_specs)
            self.provision.rest.modify_volume_snap.assert_called_once_with(
                array, source_device_id, "", snap_name,
                extra_specs, snap_id=snap_id, restore=True)

    def test_extend_volume(self):
        array = self.data.array
        device_id = self.data.device_id
        new_size = '3'
        extra_specs = self.data.extra_specs
        rdfg_num = self.data.rdf_group_no_1
        with mock.patch.object(self.provision.rest, 'extend_volume'
                               ) as mock_ex:
            self.provision.extend_volume(array, device_id, new_size,
                                         extra_specs)
            mock_ex.assert_called_once_with(
                array, device_id, new_size, extra_specs)
            mock_ex.reset_mock()
            # Pass in rdf group
            self.provision.extend_volume(array, device_id, new_size,
                                         extra_specs, rdfg_num)
            mock_ex.assert_called_once_with(
                array, device_id, new_size, extra_specs, rdfg_num)

    def test_get_srp_pool_stats(self):
        array = self.data.array
        array_info = self.common.pool_info['arrays_info'][0]
        srp_capacity = self.data.srp_details['srp_capacity']
        ref_stats = ((srp_capacity['usable_total_tb'] * 1024),
                     float((srp_capacity['usable_total_tb'] * 1024)
                           - (srp_capacity['usable_used_tb'] * 1024)),
                     (srp_capacity['subscribed_total_tb'] * 1024),
                     self.data.srp_details['reserved_cap_percent'])
        stats = self.provision.get_srp_pool_stats(array, array_info)
        self.assertEqual(ref_stats, stats)

    def test_get_srp_pool_stats_errors(self):
        # cannot retrieve srp
        array = self.data.array
        array_info = {'srpName': self.data.failed_resource}
        ref_stats = (0, 0, 0, 0, False)
        stats = self.provision.get_srp_pool_stats(array, array_info)
        self.assertEqual(ref_stats, stats)
        # cannot report on all stats
        with mock.patch.object(
                self.provision.rest, 'get_srp_by_name',
                return_value={'srp_capacity': {'usable_total_tb': 33}}):
            ref_stats = (33 * 1024, 0, 0, 0)
            stats = self.provision.get_srp_pool_stats(array, array_info)
            self.assertEqual(ref_stats, stats)

    def test_verify_slo_workload_true(self):
        # with slo and workload
        array = self.data.array
        slo = self.data.slo
        workload = self.data.workload
        srp = self.data.srp
        valid_slo, valid_workload = self.provision.verify_slo_workload(
            array, slo, workload, srp)
        self.assertTrue(valid_slo)
        self.assertTrue(valid_workload)
        # slo and workload = none
        slo2 = None
        workload2 = None
        valid_slo2, valid_workload2 = self.provision.verify_slo_workload(
            array, slo2, workload2, srp)
        self.assertTrue(valid_slo2)
        self.assertTrue(valid_workload2)
        slo2 = None
        workload2 = 'None'
        valid_slo2, valid_workload2 = self.provision.verify_slo_workload(
            array, slo2, workload2, srp)
        self.assertTrue(valid_slo2)
        self.assertTrue(valid_workload2)

    def test_verify_slo_workload_false(self):
        # Both wrong
        array = self.data.array
        slo = 'Diamante'
        workload = 'DSSS'
        srp = self.data.srp
        valid_slo, valid_workload = self.provision.verify_slo_workload(
            array, slo, workload, srp)
        self.assertFalse(valid_slo)
        self.assertFalse(valid_workload)
        # Workload set, no slo set
        valid_slo, valid_workload = self.provision.verify_slo_workload(
            array, None, self.data.workload, srp)
        self.assertTrue(valid_slo)
        self.assertFalse(valid_workload)

    def test_get_slo_workload_settings_from_storage_group(self):
        ref_settings = 'Diamond+DSS'
        sg_slo_settings = (
            self.provision.get_slo_workload_settings_from_storage_group(
                self.data.array, self.data.defaultstoragegroup_name))
        self.assertEqual(ref_settings, sg_slo_settings)
        # No workload
        with mock.patch.object(self.provision.rest, 'get_storage_group',
                               return_value={'slo': 'Silver'}):
            ref_settings2 = 'Silver+NONE'
            sg_slo_settings2 = (
                self.provision.get_slo_workload_settings_from_storage_group(
                    self.data.array, 'no_workload_sg'))
            self.assertEqual(ref_settings2, sg_slo_settings2)
        # NextGen Array
        with mock.patch.object(self.rest, 'is_next_gen_array',
                               return_value=True):
            ref_settings3 = 'Diamond+NONE'
            sg_slo_settings3 = (
                self.provision.get_slo_workload_settings_from_storage_group(
                    self.data.array, self.data.defaultstoragegroup_name))
            self.assertEqual(ref_settings3, sg_slo_settings3)

    @mock.patch.object(rest.PowerMaxRest, 'srdf_delete_device_pair')
    @mock.patch.object(rest.PowerMaxRest, 'srdf_suspend_replication')
    @mock.patch.object(rest.PowerMaxRest, 'wait_for_rdf_pair_sync')
    def test_break_rdf_relationship(self, mock_wait, mock_suspend, mock_del):
        array = self.data.array
        device_id = self.data.device_id
        sg_name = self.data.storagegroup_name_f
        rdf_group = self.data.rdf_group_no_1
        extra_specs = self.data.rep_extra_specs

        # sync still in progress
        self.provision.break_rdf_relationship(
            array, device_id, sg_name, rdf_group, extra_specs, 'SyncInProg')
        mock_wait.assert_called_once_with(array, rdf_group, device_id,
                                          extra_specs)
        mock_del.assert_called_once_with(array, rdf_group, device_id)
        mock_wait.reset_mock()
        mock_suspend.reset_mock()
        mock_del.reset_mock()

        # State is Consistent, need to suspend
        self.provision.break_rdf_relationship(
            array, device_id, sg_name, rdf_group, extra_specs, 'Consistent')
        mock_suspend.assert_called_once_with(array, sg_name, rdf_group,
                                             extra_specs)
        mock_del.assert_called_once_with(array, rdf_group, device_id)
        mock_del.reset_mock()

        # State is synchronized
        self.provision.break_rdf_relationship(
            array, device_id, sg_name, rdf_group, extra_specs, 'Synchronized')
        mock_del.assert_called_once_with(array, rdf_group, device_id)

    @mock.patch.object(rest.PowerMaxRest, 'get_storage_group',
                       return_value=None)
    def test_create_volume_group_success(self, mock_get_sg):
        array = self.data.array
        group_name = self.data.storagegroup_name_source
        extra_specs = self.data.extra_specs
        ref_value = self.data.storagegroup_name_source
        storagegroup = self.provision.create_volume_group(
            array, group_name, extra_specs)
        self.assertEqual(ref_value, storagegroup)

    def test_create_group_replica(self):
        array = self.data.array
        source_group = self.data.storagegroup_name_source
        snap_name = self.data.group_snapshot_name
        extra_specs = self.data.extra_specs
        with mock.patch.object(
                self.provision,
                'create_group_replica') as mock_create_replica:
            self.provision.create_group_replica(
                array, source_group, snap_name, extra_specs)
            mock_create_replica.assert_called_once_with(
                array, source_group, snap_name, extra_specs)

    def test_delete_group_replica(self):
        array = self.data.array
        snap_name = self.data.group_snapshot_name
        source_group_name = self.data.storagegroup_name_source
        with mock.patch.object(
                self.provision,
                'delete_group_replica') as mock_delete_replica:
            self.provision.delete_group_replica(
                array, snap_name, source_group_name)
            mock_delete_replica.assert_called_once_with(
                array, snap_name, source_group_name)

    @mock.patch.object(rest.PowerMaxRest,
                       'get_storage_group_snap_id_list',
                       side_effect=[[tpd.PowerMaxData.snap_id,
                                     tpd.PowerMaxData.snap_id_2,
                                     tpd.PowerMaxData.snap_id,
                                     tpd.PowerMaxData.snap_id_2],
                                    [tpd.PowerMaxData.snap_id,
                                     tpd.PowerMaxData.snap_id_2],
                                    [tpd.PowerMaxData.snap_id], list()])
    def test_delete_group_replica_side_effect(self, mock_list):
        array = self.data.array
        snap_name = self.data.group_snapshot_name
        source_group_name = self.data.storagegroup_name_source
        with mock.patch.object(
                self.rest, 'delete_storagegroup_snap') as mock_del:
            self.provision.delete_group_replica(
                array, snap_name, source_group_name)
            self.assertEqual(4, mock_del.call_count)
            mock_del.reset_mock()
            self.provision.delete_group_replica(
                array, snap_name, source_group_name)
            self.assertEqual(2, mock_del.call_count)
            mock_del.reset_mock()
            self.provision.delete_group_replica(
                array, snap_name, source_group_name)
            self.assertEqual(1, mock_del.call_count)
            mock_del.reset_mock()
            self.provision.delete_group_replica(
                array, snap_name, source_group_name)
            mock_del.assert_not_called()

    def test_link_and_break_replica(self):
        array = self.data.array
        source_group_name = self.data.storagegroup_name_source
        target_group_name = self.data.target_group_name
        snap_name = self.data.group_snapshot_name
        extra_specs = self.data.extra_specs
        delete_snapshot = False
        with mock.patch.object(
                self.provision,
                'link_and_break_replica') as mock_link_and_break_replica:
            self.provision.link_and_break_replica(
                array, source_group_name,
                target_group_name, snap_name,
                extra_specs, delete_snapshot)
            mock_link_and_break_replica.assert_called_once_with(
                array, source_group_name,
                target_group_name, snap_name,
                extra_specs, delete_snapshot)

    @mock.patch.object(rest.PowerMaxRest, 'get_storage_group',
                       side_effect=[None,
                                    tpd.PowerMaxData.sg_details[1]])
    @mock.patch.object(provision.PowerMaxProvision, 'create_volume_group')
    def test_get_or_create_volume_group(self, mock_create, mock_sg):
        for x in range(0, 2):
            self.provision.get_or_create_volume_group(
                self.data.array, self.data.test_group, self.data.extra_specs)
        self.assertEqual(2, mock_sg.call_count)
        self.assertEqual(1, mock_create.call_count)

    @mock.patch.object(rest.PowerMaxRest, 'create_resource',
                       return_value=(202, tpd.PowerMaxData.job_list[0]))
    def test_replicate_group(self, mock_create):
        self.rest.replicate_group(
            self.data.array, self.data.test_rep_group,
            self.data.rdf_group_no_1, self.data.remote_array,
            self.data.extra_specs)
        mock_create.assert_called_once()

    @mock.patch.object(
        rest.PowerMaxRest, 'get_snap_linked_device_list',
        side_effect=[[{'targetDevice': tpd.PowerMaxData.device_id2}],
                     [{'targetDevice': tpd.PowerMaxData.device_id2},
                      {'targetDevice': tpd.PowerMaxData.device_id3}]])
    @mock.patch.object(provision.PowerMaxProvision, '_unlink_volume')
    def test_delete_volume_snap_check_for_links(self, mock_unlink, mock_tgts):
        self.provision.delete_volume_snap_check_for_links(
            self.data.array, self.data.test_snapshot_snap_name,
            self.data.device_id, self.data.extra_specs, self.data.snap_id)
        mock_unlink.assert_called_once_with(
            self.data.array, "", "", self.data.test_snapshot_snap_name,
            self.data.extra_specs, snap_id=self.data.snap_id,
            list_volume_pairs=[
                (self.data.device_id, tpd.PowerMaxData.device_id2)])
        mock_unlink.reset_mock()
        self.provision.delete_volume_snap_check_for_links(
            self.data.array, self.data.test_snapshot_snap_name,
            self.data.device_id, self.data.extra_specs, self.data.snap_id)
        self.assertEqual(2, mock_unlink.call_count)
