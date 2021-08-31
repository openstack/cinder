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

import ast
from copy import deepcopy
import time
from unittest import mock

import six

from cinder import exception
from cinder.objects import fields
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit import test
from cinder.tests.unit.volume.drivers.dell_emc.powermax import (
    powermax_data as tpd)
from cinder.tests.unit.volume.drivers.dell_emc.powermax import (
    powermax_fake_objects as tpfo)
from cinder.volume.drivers.dell_emc.powermax import common
from cinder.volume.drivers.dell_emc.powermax import fc
from cinder.volume.drivers.dell_emc.powermax import masking
from cinder.volume.drivers.dell_emc.powermax import metadata
from cinder.volume.drivers.dell_emc.powermax import provision
from cinder.volume.drivers.dell_emc.powermax import rest
from cinder.volume.drivers.dell_emc.powermax import utils
from cinder.volume import volume_utils


class PowerMaxCommonTest(test.TestCase):
    def setUp(self):
        self.data = tpd.PowerMaxData()
        super(PowerMaxCommonTest, self).setUp()
        self.mock_object(volume_utils, 'get_max_over_subscription_ratio',
                         return_value=1.0)
        replication_device = self.data.sync_rep_device
        configuration = tpfo.FakeConfiguration(
            emc_file=None, volume_backend_name='CommonTests', interval=1,
            retries=1, san_ip='1.1.1.1', san_login='smc',
            powermax_array=self.data.array, powermax_srp='SRP_1',
            san_password='smc', san_api_port=8443,
            powermax_port_groups=[self.data.port_group_name_f],
            powermax_port_group_name_template='portGroupName',
            replication_device=replication_device)
        rest.PowerMaxRest._establish_rest_session = mock.Mock(
            return_value=tpfo.FakeRequestsSession())
        driver = fc.PowerMaxFCDriver(configuration=configuration)
        self.driver = driver
        self.common = self.driver.common
        self.masking = self.common.masking
        self.provision = self.common.provision
        self.rest = self.common.rest
        self.utils = self.common.utils
        self.utils.get_volumetype_extra_specs = (
            mock.Mock(return_value=self.data.vol_type_extra_specs))
        self.rest.is_snap_id = True

    @mock.patch.object(rest.PowerMaxRest, 'get_array_ucode_version',
                       return_value=tpd.PowerMaxData.next_gen_ucode)
    @mock.patch.object(rest.PowerMaxRest, 'get_array_model_info',
                       return_value=('PowerMax 2000', True))
    @mock.patch.object(rest.PowerMaxRest, 'set_rest_credentials')
    @mock.patch.object(common.PowerMaxCommon, '_get_slo_workload_combinations',
                       return_value=[])
    @mock.patch.object(common.PowerMaxCommon,
                       'get_attributes_from_cinder_config',
                       side_effect=[[], tpd.PowerMaxData.array_info_wl])
    def test_gather_info_tests(self, mck_parse, mck_combo, mck_rest,
                               mck_nextgen, mck_ucode):
        # Use-Case 1: Gather info no-opts
        configuration = tpfo.FakeConfiguration(
            None, 'config_group', None, None)
        fc.PowerMaxFCDriver(configuration=configuration)

        # Use-Case 2: Gather info next-gen with ucode/version
        self.common._gather_info()
        self.assertTrue(self.common.next_gen)
        self.assertEqual(self.common.ucode_level, self.data.next_gen_ucode)

    @mock.patch.object(rest.PowerMaxRest, 'get_array_ucode_version',
                       return_value=tpd.PowerMaxData.next_gen_ucode)
    @mock.patch.object(rest.PowerMaxRest, 'get_array_model_info',
                       return_value=('PowerMax 2000', True))
    @mock.patch.object(rest.PowerMaxRest, 'set_rest_credentials')
    @mock.patch.object(
        common.PowerMaxCommon, 'get_attributes_from_cinder_config',
        return_value={'SerialNumber': tpd.PowerMaxData.array})
    @mock.patch.object(
        common.PowerMaxCommon, '_get_attributes_from_config')
    def test_gather_info_rep_enabled_duplicate_serial_numbers(
            self, mck_get_cnf, mck_get_c_cnf, mck_set, mck_model, mck_ucode):
        is_enabled = self.common.replication_enabled
        targets = self.common.replication_targets
        self.common.replication_enabled = True
        self.common.replication_targets = [self.data.array]
        self.assertRaises(
            exception.InvalidConfigurationValue, self.common._gather_info)
        self.common.replication_enabled = is_enabled
        self.common.replication_targets = targets

    @mock.patch.object(common.PowerMaxCommon,
                       '_gather_info')
    def test_get_attributes_from_config_short_host_template(
            self, mock_gather):
        configuration = tpfo.FakeConfiguration(
            emc_file=None, volume_backend_name='config_group', interval='10',
            retries='10', replication_device=None,
            powermax_short_host_name_template='shortHostName')
        driver = fc.PowerMaxFCDriver(configuration=configuration)
        driver.common._get_attributes_from_config()
        self.assertEqual(
            'shortHostName', driver.common.powermax_short_host_name_template)

    @mock.patch.object(common.PowerMaxCommon,
                       '_gather_info')
    def test_get_attributes_from_config_no_short_host_template(
            self, mock_gather):
        configuration = tpfo.FakeConfiguration(
            emc_file=None, volume_backend_name='config_group', interval='10',
            retries='10', replication_device=None)
        driver = fc.PowerMaxFCDriver(configuration=configuration)
        driver.common._get_attributes_from_config()
        self.assertIsNone(driver.common.powermax_short_host_name_template)

    @mock.patch.object(common.PowerMaxCommon,
                       '_gather_info')
    def test_get_attributes_from_config_port_group_template(
            self, mock_gather):
        configuration = tpfo.FakeConfiguration(
            emc_file=None, volume_backend_name='config_group', interval='10',
            retries='10', replication_device=None,
            powermax_port_group_name_template='portGroupName')
        driver = fc.PowerMaxFCDriver(configuration=configuration)
        driver.common._get_attributes_from_config()
        self.assertEqual(
            'portGroupName', driver.common.powermax_port_group_name_template)

    @mock.patch.object(common.PowerMaxCommon,
                       '_gather_info')
    def test_get_attributes_from_config_no_port_group_template(
            self, mock_gather):
        configuration = tpfo.FakeConfiguration(
            emc_file=None, volume_backend_name='config_group', interval='10',
            retries='10', replication_device=None)
        driver = fc.PowerMaxFCDriver(configuration=configuration)
        driver.common._get_attributes_from_config()
        self.assertIsNone(driver.common.powermax_port_group_name_template)

    def test_get_slo_workload_combinations_powermax(self):
        self.common.next_gen = True
        self.common.array_model = 'PowerMax_2000'
        array_info = {}
        pools = self.common._get_slo_workload_combinations(array_info)
        self.assertTrue(len(pools) == 24)

    def test_get_slo_workload_combinations_afa_powermax(self):
        self.common.next_gen = True
        self.common.array_model = 'VMAX250F'
        array_info = {}
        pools = self.common._get_slo_workload_combinations(array_info)
        self.assertTrue(len(pools) == 28)

    def test_get_slo_workload_combinations_afa_hypermax(self):
        self.common.next_gen = False
        self.common.array_model = 'VMAX250F'
        array_info = {}
        pools = self.common._get_slo_workload_combinations(array_info)
        self.assertTrue(len(pools) == 16)

    def test_get_slo_workload_combinations_hybrid(self):
        self.common.next_gen = False
        self.common.array_model = 'VMAX100K'
        array_info = {}
        pools = self.common._get_slo_workload_combinations(array_info)
        self.assertTrue(len(pools) == 44)

    def test_get_slo_workload_combinations_failed(self):
        self.common.array_model = 'xxxxxx'
        array_info = {}
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.common._get_slo_workload_combinations, array_info)

    @mock.patch.object(
        common.PowerMaxCommon, 'get_volume_metadata',
        return_value={'device-meta-key-1': 'device-meta-value-1',
                      'device-meta-key-2': 'device-meta-value-2'})
    def test_create_volume(self, mck_meta):
        ref_model_update = (
            {'provider_location': six.text_type(self.data.provider_location),
             'metadata': {'device-meta-key-1': 'device-meta-value-1',
                          'device-meta-key-2': 'device-meta-value-2',
                          'user-meta-key-1': 'user-meta-value-1',
                          'user-meta-key-2': 'user-meta-value-2'}})
        volume = deepcopy(self.data.test_volume)
        volume.metadata = {'user-meta-key-1': 'user-meta-value-1',
                           'user-meta-key-2': 'user-meta-value-2'}
        model_update = self.common.create_volume(volume)
        self.assertEqual(ref_model_update, model_update)

    @mock.patch.object(common.PowerMaxCommon, 'get_volume_metadata',
                       return_value=tpd.PowerMaxData.volume_metadata)
    def test_create_volume_qos(self, mck_meta):
        ref_model_update = (
            {'provider_location': six.text_type(self.data.provider_location),
             'metadata': self.data.volume_metadata})
        extra_specs = deepcopy(self.data.extra_specs_intervals_set)
        extra_specs['qos'] = {
            'total_iops_sec': '4000', 'DistributionType': 'Always'}
        with mock.patch.object(self.utils, 'get_volumetype_extra_specs',
                               return_value=extra_specs):
            model_update = self.common.create_volume(self.data.test_volume)
            self.assertEqual(ref_model_update, model_update)

    @mock.patch.object(common.PowerMaxCommon, '_cleanup_device_snapvx')
    @mock.patch.object(common.PowerMaxCommon, 'get_volume_metadata',
                       return_value='')
    def test_create_volume_from_snapshot(self, mck_meta, mck_cleanup_snaps):
        ref_model_update = ({'provider_location': six.text_type(
            deepcopy(self.data.provider_location_snapshot))})
        model_update = self.common.create_volume_from_snapshot(
            self.data.test_clone_volume, self.data.test_snapshot)
        self.assertEqual(
            ast.literal_eval(ref_model_update['provider_location']),
            ast.literal_eval(model_update['provider_location']))

        # Test from legacy snapshot
        ref_model_update = (
            {'provider_location': six.text_type(
                deepcopy(self.data.provider_location_clone))})
        model_update = self.common.create_volume_from_snapshot(
            self.data.test_clone_volume, self.data.test_legacy_snapshot)
        self.assertEqual(
            ast.literal_eval(ref_model_update['provider_location']),
            ast.literal_eval(model_update['provider_location']))

    @mock.patch.object(common.PowerMaxCommon, 'gather_replication_updates',
                       return_value=(tpd.PowerMaxData.replication_update,
                                     tpd.PowerMaxData.rep_info_dict))
    @mock.patch.object(common.PowerMaxCommon, 'srdf_protect_storage_group')
    @mock.patch.object(provision.PowerMaxProvision, 'create_volume_from_sg',
                       return_value=tpd.PowerMaxData.volume_create_info_dict)
    @mock.patch.object(common.PowerMaxCommon, 'prepare_replication_details',
                       return_value=(True, tpd.PowerMaxData.rep_extra_specs5,
                                     tpd.PowerMaxData.rep_info_dict, True))
    def test_create_replication_enabled_volume_first_volume(
            self, mck_prep, mck_create, mck_protect, mck_updates):
        array = self.data.array
        volume = self.data.test_volume
        volume_name = volume.name
        volume_size = volume.size
        rep_extra_specs = self.data.rep_extra_specs
        rep_extra_specs5 = self.data.rep_extra_specs5
        storagegroup_name = self.data.storagegroup_name_f
        rep_info_dict = self.data.rep_info_dict
        rep_vol = deepcopy(self.data.volume_create_info_dict)
        rep_vol.update({'device_uuid': volume_name,
                        'storage_group': storagegroup_name,
                        'size': volume_size})
        vol, update, info = self.common._create_replication_enabled_volume(
            array, volume, volume_name, volume_size, rep_extra_specs,
            storagegroup_name, rep_extra_specs['rep_mode'])
        mck_prep.assert_called_once_with(self.data.rep_extra_specs)
        mck_create.assert_called_once_with(
            array, volume_name, storagegroup_name, volume_size,
            rep_extra_specs, rep_info_dict)
        mck_protect.assert_called_once_with(
            rep_extra_specs, rep_extra_specs5, rep_vol)
        rep_vol.update({'remote_device_id': self.data.device_id2})
        mck_updates.assert_called_once_with(
            rep_extra_specs, rep_extra_specs5, rep_vol)
        self.assertEqual(self.data.volume_create_info_dict, vol)
        self.assertEqual(self.data.replication_update, update)
        self.assertEqual(self.data.rep_info_dict, info)

    @mock.patch.object(common.PowerMaxCommon, '_validate_rdfg_status')
    @mock.patch.object(common.PowerMaxCommon, 'gather_replication_updates',
                       return_value=(tpd.PowerMaxData.replication_update,
                                     tpd.PowerMaxData.rep_info_dict))
    @mock.patch.object(common.PowerMaxCommon, 'srdf_protect_storage_group')
    @mock.patch.object(provision.PowerMaxProvision, 'create_volume_from_sg',
                       return_value=tpd.PowerMaxData.volume_create_info_dict)
    @mock.patch.object(common.PowerMaxCommon, 'prepare_replication_details',
                       side_effect=((False, '', '', True),
                                    ('', tpd.PowerMaxData.rep_extra_specs5,
                                     tpd.PowerMaxData.rep_info_dict, '')))
    def test_create_replication_enabled_volume_not_first_volume(
            self, mck_prepare, mck_create, mck_protect, mck_updates,
            mck_valid):
        array = self.data.array
        volume = self.data.test_volume
        volume_name = volume.name
        volume_size = volume.size
        rep_extra_specs = self.data.rep_extra_specs
        rep_extra_specs5 = self.data.rep_extra_specs5
        storagegroup_name = self.data.storagegroup_name_f
        rep_info_dict = self.data.rep_info_dict
        rep_vol = deepcopy(self.data.volume_create_info_dict)
        rep_vol.update({'device_uuid': volume_name,
                        'storage_group': storagegroup_name,
                        'size': volume_size})
        vol, update, info = self.common._create_replication_enabled_volume(
            array, volume, volume_name, volume_size, rep_extra_specs,
            storagegroup_name, rep_extra_specs['rep_mode'])
        self.assertEqual(2, mck_prepare.call_count)
        mck_create.assert_called_once_with(
            array, volume_name, storagegroup_name, volume_size,
            rep_extra_specs, rep_info_dict)
        mck_protect.assert_not_called()
        mck_valid.assert_called_once_with(array, rep_extra_specs)
        rep_vol.update({'remote_device_id': self.data.device_id2})
        mck_updates.assert_called_once_with(
            rep_extra_specs, rep_extra_specs5, rep_vol)
        self.assertEqual(self.data.volume_create_info_dict, vol)
        self.assertEqual(self.data.replication_update, update)
        self.assertEqual(self.data.rep_info_dict, info)

    @mock.patch.object(common.PowerMaxCommon, 'gather_replication_updates',
                       return_value=(tpd.PowerMaxData.replication_update,
                                     tpd.PowerMaxData.rep_info_dict))
    @mock.patch.object(common.PowerMaxCommon, 'get_and_set_remote_device_uuid',
                       return_value=tpd.PowerMaxData.device_id2)
    @mock.patch.object(rest.PowerMaxRest, 'srdf_resume_replication')
    @mock.patch.object(
        common.PowerMaxCommon, 'configure_volume_replication',
        return_value=(None, None, None, tpd.PowerMaxData.rep_extra_specs_mgmt,
                      True))
    @mock.patch.object(common.PowerMaxCommon, 'srdf_protect_storage_group')
    @mock.patch.object(provision.PowerMaxProvision, 'create_volume_from_sg',
                       return_value=tpd.PowerMaxData.volume_create_info_dict)
    @mock.patch.object(common.PowerMaxCommon, 'prepare_replication_details',
                       return_value=(True, {}, {}, False))
    def test_create_replication_enabled_volume_not_first_rdfg_volume(
            self, mck_prepare, mck_create, mck_protect, mck_configure,
            mck_resume, mck_get_set, mck_updates):

        array = self.data.array
        volume = self.data.test_volume
        volume_name = volume.name
        volume_size = volume.size
        rep_extra_specs = self.data.rep_extra_specs
        storagegroup_name = self.data.storagegroup_name_f

        self.common._create_replication_enabled_volume(
            array, volume, volume_name, volume_size, rep_extra_specs,
            storagegroup_name, rep_extra_specs['rep_mode'])

        mck_prepare.assert_called_once()
        mck_protect.assert_not_called()
        mck_configure.assert_called_once()
        mck_resume.assert_called_once()

    @mock.patch.object(common.PowerMaxCommon, '_cleanup_device_snapvx')
    @mock.patch.object(common.PowerMaxCommon, 'get_volume_metadata',
                       return_value='')
    def test_cloned_volume(self, mck_meta, mck_cleanup_snaps):
        array = self.data.array
        test_volume = self.data.test_clone_volume
        source_device_id = self.data.device_id
        extra_specs = self.common._initial_setup(test_volume)
        ref_model_update = ({'provider_location': six.text_type(
            self.data.provider_location_clone)})
        model_update = self.common.create_cloned_volume(
            self.data.test_clone_volume, self.data.test_volume)
        self.assertEqual(
            ast.literal_eval(ref_model_update['provider_location']),
            ast.literal_eval(model_update['provider_location']))
        mck_cleanup_snaps.assert_called_once_with(
            array, source_device_id, extra_specs)

    @mock.patch.object(rest.PowerMaxRest, 'get_volume_snapshot_list',
                       return_value=list())
    def test_delete_volume(self, mck_get_snaps):
        with mock.patch.object(self.common, '_delete_volume') as mock_delete:
            self.common.delete_volume(self.data.test_volume)
            mock_delete.assert_called_once_with(self.data.test_volume)

    @mock.patch.object(common.PowerMaxCommon, '_delete_from_srp')
    @mock.patch.object(common.PowerMaxCommon, '_cleanup_device_snapvx')
    @mock.patch.object(rest.PowerMaxRest, 'get_volume_snap_info',
                       return_value=tpd.PowerMaxData.volume_snap_vx)
    def test_delete_volume_fail_if_active_snapshots(
            self, mck_get_snaps, mck_cleanup, mck_delete):
        array = self.data.array
        test_volume = self.data.test_volume
        device_id = self.data.device_id
        extra_specs = self.common._initial_setup(test_volume)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common._delete_volume, test_volume)
        mck_cleanup.assert_called_once_with(array, device_id, extra_specs)
        mck_delete.assert_not_called()

    @mock.patch.object(common.PowerMaxCommon, '_delete_from_srp')
    @mock.patch.object(common.PowerMaxCommon, '_cleanup_device_snapvx')
    @mock.patch.object(
        rest.PowerMaxRest, 'find_snap_vx_sessions',
        return_value=('', tpd.PowerMaxData.snap_tgt_session_cm_enabled))
    @mock.patch.object(rest.PowerMaxRest, 'get_volume_snapshot_list',
                       return_value=list())
    def test_delete_volume_fail_if_snapvx_target(
            self, mck_get_snaps, mck_tgt_snap, mck_cleanup, mck_delete):
        array = self.data.array
        test_volume = self.data.test_volume
        device_id = self.data.device_id
        extra_specs = self.common._initial_setup(test_volume)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common._delete_volume, test_volume)
        mck_cleanup.assert_called_once_with(array, device_id, extra_specs)
        mck_delete.assert_not_called()

    @mock.patch.object(common.PowerMaxCommon, '_cleanup_device_snapvx')
    @mock.patch.object(
        common.PowerMaxCommon, 'get_snapshot_metadata',
        return_value={'snap-meta-key-1': 'snap-meta-value-1',
                      'snap-meta-key-2': 'snap-meta-value-2'})
    def test_create_snapshot(self, mck_meta, mck_cleanup_snaps):
        ref_model_update = (
            {'provider_location': six.text_type(self.data.snap_location),
             'metadata': {'snap-meta-key-1': 'snap-meta-value-1',
                          'snap-meta-key-2': 'snap-meta-value-2',
                          'user-meta-key-1': 'user-meta-value-1',
                          'user-meta-key-2': 'user-meta-value-2'}})
        snapshot = deepcopy(self.data.test_snapshot_manage)
        snapshot.metadata = {'user-meta-key-1': 'user-meta-value-1',
                             'user-meta-key-2': 'user-meta-value-2'}
        model_update = self.common.create_snapshot(
            snapshot, self.data.test_volume)
        self.assertEqual(ref_model_update, model_update)

    @mock.patch.object(
        common.PowerMaxCommon, '_parse_snap_info',
        return_value=(tpd.PowerMaxData.device_id,
                      tpd.PowerMaxData.snap_location['snap_name'],
                      [tpd.PowerMaxData.snap_id]))
    def test_delete_snapshot(self, mock_parse):
        snap_name = self.data.snap_location['snap_name']
        sourcedevice_id = self.data.snap_location['source_id']
        with mock.patch.object(
                self.provision, 'delete_volume_snap') as mock_delete_snap:
            self.common.delete_snapshot(
                self.data.test_snapshot, self.data.test_volume)
            mock_delete_snap.assert_called_once_with(
                self.data.array, snap_name, [sourcedevice_id],
                self.data.snap_id, restored=False)

    def test_delete_snapshot_not_found(self):
        with mock.patch.object(self.common, '_parse_snap_info',
                               return_value=(None, 'Something', None)):
            with mock.patch.object(
                    self.provision, 'delete_volume_snap') as mock_delete_snap:
                self.common.delete_snapshot(self.data.test_snapshot,
                                            self.data.test_volume)
                mock_delete_snap.assert_not_called()

    def test_delete_legacy_snap(self):
        with mock.patch.object(self.common, '_delete_volume') as mock_del:
            self.common.delete_snapshot(self.data.test_legacy_snapshot,
                                        self.data.test_legacy_vol)
            mock_del.assert_called_once_with(self.data.test_legacy_snapshot)

    @mock.patch.object(masking.PowerMaxMasking,
                       'return_volume_to_fast_managed_group')
    @mock.patch.object(masking.PowerMaxMasking, 'remove_and_reset_members')
    def test_remove_members(self, mock_rm, mock_return):
        array = self.data.array
        device_id = self.data.device_id
        volume = self.data.test_volume
        volume_name = self.data.test_volume.name
        extra_specs = self.data.extra_specs
        self.common._remove_members(
            array, volume, device_id, extra_specs, self.data.connector, False)
        mock_rm.assert_called_once_with(
            array, volume, device_id, volume_name,
            extra_specs, True, self.data.connector, async_grp=None,
            host_template=None)

    @mock.patch.object(masking.PowerMaxMasking,
                       'return_volume_to_fast_managed_group')
    @mock.patch.object(masking.PowerMaxMasking, 'remove_and_reset_members')
    def test_remove_members_multiattach_case(self, mock_rm, mock_return):
        array = self.data.array
        device_id = self.data.device_id
        volume = self.data.test_volume
        volume_name = self.data.test_volume.name
        extra_specs = self.data.extra_specs
        self.common._remove_members(
            array, volume, device_id, extra_specs, self.data.connector, True)
        mock_rm.assert_called_once_with(
            array, volume, device_id, volume_name,
            extra_specs, False, self.data.connector, async_grp=None,
            host_template=None)
        mock_return.assert_called_once()

    def test_unmap_lun(self):
        array = self.data.array
        device_id = self.data.device_id
        volume = self.data.test_volume
        extra_specs = deepcopy(self.data.extra_specs_intervals_set)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        connector = self.data.connector
        with mock.patch.object(self.common, '_remove_members') as mock_remove:
            self.common._unmap_lun(volume, connector)
            mock_remove.assert_called_once_with(
                array, volume, device_id, extra_specs,
                connector, False, async_grp=None, host_template=None)

    def test_unmap_lun_force(self):
        volume = self.data.test_volume
        extra_specs = deepcopy(self.data.extra_specs_intervals_set)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        connector = deepcopy(self.data.connector)
        del connector['host']
        with mock.patch.object(
                self.common.utils, 'get_host_short_name') as mock_host:
            self.common._unmap_lun(volume, connector)
            mock_host.assert_not_called()

    @mock.patch.object(common.PowerMaxCommon, '_remove_members')
    def test_unmap_lun_attachments(self, mock_rm):
        volume1 = deepcopy(self.data.test_volume)
        volume1.volume_attachment.objects = [self.data.test_volume_attachment]
        connector = self.data.connector
        self.common._unmap_lun(volume1, connector)
        mock_rm.assert_called_once()
        mock_rm.reset_mock()
        volume2 = deepcopy(volume1)
        volume2.volume_attachment.objects.append(
            self.data.test_volume_attachment)
        self.common._unmap_lun(volume2, connector)
        mock_rm.assert_not_called()

    def test_unmap_lun_qos(self):
        array = self.data.array
        device_id = self.data.device_id
        volume = self.data.test_volume
        extra_specs = deepcopy(self.data.extra_specs_intervals_set)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        extra_specs['qos'] = {
            'total_iops_sec': '4000', 'DistributionType': 'Always'}
        connector = self.data.connector
        with mock.patch.object(self.common, '_remove_members') as mock_remove:
            with mock.patch.object(self.utils, 'get_volumetype_extra_specs',
                                   return_value=extra_specs):
                self.common._unmap_lun(volume, connector)
                mock_remove.assert_called_once_with(
                    array, volume, device_id, extra_specs,
                    connector, False, async_grp=None, host_template=None)

    def test_unmap_lun_not_mapped(self):
        volume = self.data.test_volume
        connector = self.data.connector
        with mock.patch.object(self.common, 'find_host_lun_id',
                               return_value=({}, False)):
            with mock.patch.object(
                    self.common, '_remove_members') as mock_remove:
                self.common._unmap_lun(volume, connector)
                mock_remove.assert_not_called()

    def test_unmap_lun_connector_is_none(self):
        array = self.data.array
        device_id = self.data.device_id
        volume = self.data.test_volume
        extra_specs = deepcopy(self.data.extra_specs_intervals_set)
        extra_specs['storagetype:portgroupname'] = (
            self.data.port_group_name_f)
        with mock.patch.object(self.common, '_remove_members') as mock_remove:
            self.common._unmap_lun(volume, None)
            mock_remove.assert_called_once_with(
                array, volume, device_id, extra_specs, None,
                False, async_grp=None, host_template=None)

    @mock.patch.object(metadata.PowerMaxVolumeMetadata, 'capture_detach_info')
    @mock.patch.object(common.PowerMaxCommon, '_remove_members')
    def test_unmap_lun_multiattach_prints_metadata(self, mck_remove, mck_info):
        volume = deepcopy(self.data.test_volume)
        connector = deepcopy(self.data.connector)
        volume.volume_attachment.objects = [
            deepcopy(self.data.test_volume_attachment),
            deepcopy(self.data.test_volume_attachment)]
        self.common._unmap_lun(volume, connector)
        self.assertEqual(0, mck_remove.call_count)
        self.assertEqual(1, mck_info.call_count)

    @mock.patch.object(provision.PowerMaxProvision, 'verify_slo_workload')
    @mock.patch.object(common.PowerMaxCommon, '_remove_members')
    @mock.patch.object(common.PowerMaxCommon, 'find_host_lun_id',
                       return_value=(tpd.PowerMaxData.iscsi_device_info,
                                     False))
    @mock.patch.object(
        common.PowerMaxCommon, '_get_replication_extra_specs',
        return_value=tpd.PowerMaxData.rep_extra_specs_rep_config)
    @mock.patch.object(
        common.PowerMaxCommon, '_initial_setup',
        return_value=tpd.PowerMaxData.rep_extra_specs_rep_config)
    def test_unmap_lun_replication_force_flag(
            self, mck_setup, mck_rep, mck_find, mck_rem, mck_slo):
        volume = deepcopy(self.data.test_volume)
        connector = deepcopy(self.data.connector)
        device_info = self.data.provider_location['device_id']
        volume.volume_attachment.objects = [
            deepcopy(self.data.test_volume_attachment)]
        extra_specs = deepcopy(self.data.rep_extra_specs_rep_config)
        array = extra_specs[utils.ARRAY]
        extra_specs[utils.FORCE_VOL_EDIT] = True
        self.common._unmap_lun(volume, connector)
        mck_rem.assert_called_once_with(array, volume, device_info,
                                        extra_specs, connector, False,
                                        async_grp=None, host_template=None)

    @mock.patch.object(utils.PowerMaxUtils, 'is_metro_device',
                       return_value=True)
    @mock.patch.object(provision.PowerMaxProvision, 'verify_slo_workload')
    @mock.patch.object(common.PowerMaxCommon, '_remove_members')
    @mock.patch.object(common.PowerMaxCommon, 'find_host_lun_id',
                       return_value=(tpd.PowerMaxData.iscsi_device_info,
                                     False))
    @mock.patch.object(
        common.PowerMaxCommon, '_get_replication_extra_specs',
        return_value=tpd.PowerMaxData.rep_extra_specs_rep_config_metro)
    @mock.patch.object(
        common.PowerMaxCommon, '_initial_setup',
        return_value=tpd.PowerMaxData.rep_extra_specs_rep_config_metro)
    def test_unmap_lun_replication_metro(
            self, mck_setup, mck_rep, mck_find, mck_rem, mck_slo, mck_metro):
        volume = deepcopy(self.data.test_volume)
        connector = deepcopy(self.data.connector)
        volume.volume_attachment.objects = [
            deepcopy(self.data.test_volume_attachment)]
        extra_specs = deepcopy(self.data.rep_extra_specs_rep_config)
        extra_specs[utils.FORCE_VOL_EDIT] = True
        self.common._unmap_lun(volume, connector)
        self.assertEqual(2, mck_rem.call_count)

    @mock.patch.object(utils.PowerMaxUtils, 'is_metro_device',
                       return_value=True)
    @mock.patch.object(provision.PowerMaxProvision, 'verify_slo_workload')
    @mock.patch.object(common.PowerMaxCommon, '_remove_members')
    @mock.patch.object(common.PowerMaxCommon, 'find_host_lun_id',
                       return_value=(tpd.PowerMaxData.iscsi_device_info,
                                     False))
    @mock.patch.object(
        common.PowerMaxCommon, '_get_replication_extra_specs',
        return_value=tpd.PowerMaxData.rep_extra_specs_rep_config_metro)
    @mock.patch.object(
        common.PowerMaxCommon, '_initial_setup',
        return_value=tpd.PowerMaxData.rep_extra_specs_rep_config_metro)
    def test_unmap_lun_replication_metro_promotion(
            self, mck_setup, mck_rep, mck_find, mck_rem, mck_slo, mck_metro):
        volume = deepcopy(self.data.test_volume)
        connector = deepcopy(self.data.connector)
        volume.volume_attachment.objects = [
            deepcopy(self.data.test_volume_attachment)]
        extra_specs = deepcopy(self.data.rep_extra_specs_rep_config)
        extra_specs[utils.FORCE_VOL_EDIT] = True
        self.common.promotion = True
        self.common._unmap_lun(volume, connector)
        self.common.promotion = False
        self.assertEqual(1, mck_rem.call_count)

    @mock.patch.object(common.PowerMaxCommon, '_unmap_lun')
    @mock.patch.object(metadata.PowerMaxVolumeMetadata, 'capture_detach_info')
    def test_unmap_lun_promotion_non_replicated_volume(
            self, mck_unmap, mck_info):
        volume = deepcopy(self.data.test_volume)
        connector = deepcopy(self.data.connector)
        self.common._unmap_lun_promotion(volume, connector)
        self.assertEqual(0, mck_unmap.call_count)
        self.assertEqual(0, mck_info.call_count)

    @mock.patch.object(common.PowerMaxCommon, '_unmap_lun')
    @mock.patch.object(
        common.PowerMaxCommon, '_initial_setup',
        return_value=tpd.PowerMaxData.rep_extra_specs_rep_config_metro)
    def test_unmap_lun_promotion_replicated_metro_volume(
            self, mck_setup, mck_unmap):
        volume = deepcopy(self.data.test_rep_volume)
        connector = deepcopy(self.data.connector)
        self.common._unmap_lun_promotion(volume, connector)
        mck_setup.assert_called_once_with(volume)
        mck_unmap.assert_called_once_with(volume, connector)

    @mock.patch.object(metadata.PowerMaxVolumeMetadata, 'capture_detach_info')
    @mock.patch.object(
        common.PowerMaxCommon, '_initial_setup',
        return_value=tpd.PowerMaxData.rep_extra_specs_rep_config)
    def test_unmap_lun_promotion_replicated_non_metro_volume(
            self, mck_setup, mck_capture):
        volume = deepcopy(self.data.test_rep_volume)
        connector = deepcopy(self.data.connector)
        extra_specs = self.data.rep_extra_specs_rep_config
        device_id = self.data.device_id
        promotion_key = [utils.PMAX_FAILOVER_START_ARRAY_PROMOTION]
        self.common._unmap_lun_promotion(volume, connector)
        mck_setup.assert_called_once_with(volume)
        mck_capture.assert_called_once_with(
            volume, extra_specs, device_id, promotion_key, promotion_key)

    def test_initialize_connection_already_mapped(self):
        volume = self.data.test_volume
        connector = self.data.connector
        host_lun = (self.data.maskingview[0]['maskingViewConnection'][0][
            'host_lun_address'])
        ref_dict = {'hostlunid': int(host_lun, 16),
                    'maskingview': self.data.masking_view_name_f,
                    'array': self.data.array,
                    'device_id': self.data.device_id}
        device_info_dict = self.common.initialize_connection(volume, connector)
        self.assertEqual(ref_dict, device_info_dict)

    def test_initialize_connection_setup_init_conn(self):
        volume = self.data.test_volume
        connector = self.data.connector
        with mock.patch.object(
                self.common, '_initial_setup',
                side_effect=self.common._initial_setup) as mck_setup:
            self.common.initialize_connection(volume, connector)
            mck_setup.assert_called_once_with(volume, init_conn=True)

    def test_initialize_connection_already_mapped_next_gen(self):
        with mock.patch.object(self.rest, 'is_next_gen_array',
                               return_value=True):
            volume = self.data.test_volume
            connector = self.data.connector
            host_lun = (self.data.maskingview[0]['maskingViewConnection'][0][
                'host_lun_address'])
            ref_dict = {'hostlunid': int(host_lun, 16),
                        'maskingview': self.data.masking_view_name_f,
                        'array': self.data.array,
                        'device_id': self.data.device_id}
            device_info_dict = self.common.initialize_connection(volume,
                                                                 connector)
            self.assertEqual(ref_dict, device_info_dict)

    @mock.patch.object(common.PowerMaxCommon, 'find_host_lun_id',
                       return_value=({}, False))
    @mock.patch.object(
        common.PowerMaxCommon, '_attach_volume',
        return_value=({}, tpd.PowerMaxData.port_group_name_f))
    def test_initialize_connection_not_mapped(self, mock_attach, mock_id):
        volume = self.data.test_volume
        connector = self.data.connector
        extra_specs = deepcopy(self.data.extra_specs_intervals_set)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        masking_view_dict = self.common._populate_masking_dict(
            volume, connector, extra_specs)
        masking_view_dict[utils.IS_MULTIATTACH] = False
        device_info_dict = self.common.initialize_connection(
            volume, connector)
        self.assertEqual({}, device_info_dict)
        mock_attach.assert_called_once_with(
            volume, connector, extra_specs, masking_view_dict)

    @mock.patch.object(rest.PowerMaxRest, 'is_next_gen_array',
                       return_value=True)
    @mock.patch.object(common.PowerMaxCommon, 'find_host_lun_id',
                       return_value=({}, False))
    @mock.patch.object(
        common.PowerMaxCommon, '_attach_volume',
        return_value=({}, tpd.PowerMaxData.port_group_name_f))
    def test_initialize_connection_not_mapped_next_gen(self, mock_attach,
                                                       mock_id, mck_gen):
        volume = self.data.test_volume
        connector = self.data.connector
        device_info_dict = self.common.initialize_connection(
            volume, connector)
        self.assertEqual({}, device_info_dict)

    @mock.patch.object(
        masking.PowerMaxMasking, 'pre_multiattach',
        return_value=tpd.PowerMaxData.masking_view_dict_multiattach)
    @mock.patch.object(common.PowerMaxCommon, 'find_host_lun_id',
                       return_value=({}, True))
    @mock.patch.object(
        common.PowerMaxCommon, '_attach_volume',
        return_value=({}, tpd.PowerMaxData.port_group_name_f))
    def test_initialize_connection_multiattach_case(
            self, mock_attach, mock_id, mock_pre):
        volume = self.data.test_volume
        connector = self.data.connector
        self.common.initialize_connection(volume, connector)
        mock_attach.assert_called_once()
        mock_pre.assert_called_once()

    def test_attach_volume_success(self):
        volume = self.data.test_volume
        connector = self.data.connector
        extra_specs = deepcopy(self.data.extra_specs)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        masking_view_dict = self.common._populate_masking_dict(
            volume, connector, extra_specs)
        host_lun = (self.data.maskingview[0]['maskingViewConnection'][0][
            'host_lun_address'])
        ref_dict = {'hostlunid': int(host_lun, 16),
                    'maskingview': self.data.masking_view_name_f,
                    'array': self.data.array,
                    'device_id': self.data.device_id}
        with mock.patch.object(self.masking, 'setup_masking_view',
                               return_value={
                                   utils.PORTGROUPNAME:
                                       self.data.port_group_name_f}):
            device_info_dict, pg = self.common._attach_volume(
                volume, connector, extra_specs, masking_view_dict)
        self.assertEqual(ref_dict, device_info_dict)

    @mock.patch.object(masking.PowerMaxMasking,
                       'check_if_rollback_action_for_masking_required')
    @mock.patch.object(masking.PowerMaxMasking, 'setup_masking_view',
                       return_value={})
    @mock.patch.object(common.PowerMaxCommon, 'find_host_lun_id',
                       return_value=({}, False))
    def test_attach_volume_failed(self, mock_lun, mock_setup, mock_rollback):
        volume = self.data.test_volume
        connector = self.data.connector
        extra_specs = deepcopy(self.data.extra_specs)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        masking_view_dict = self.common._populate_masking_dict(
            volume, connector, extra_specs)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common._attach_volume, volume,
                          connector, extra_specs, masking_view_dict)
        device_id = self.data.device_id
        (mock_rollback.assert_called_once_with(
            self.data.array, volume, device_id, {}))

    def test_terminate_connection(self):
        volume = self.data.test_volume
        connector = self.data.connector
        with mock.patch.object(self.common, '_unmap_lun') as mock_unmap:
            self.common.terminate_connection(volume, connector)
            mock_unmap.assert_called_once_with(
                volume, connector)

    def test_terminate_connection_promotion(self):
        volume = self.data.test_volume
        connector = self.data.connector
        with mock.patch.object(
                self.common, '_unmap_lun_promotion') as mock_unmap:
            self.common.promotion = True
            self.common.terminate_connection(volume, connector)
            mock_unmap.assert_called_once_with(
                volume, connector)
            self.common.promotion = False

    @mock.patch.object(provision.PowerMaxProvision, 'extend_volume')
    @mock.patch.object(common.PowerMaxCommon, '_extend_vol_validation_checks')
    def test_extend_vol_no_rep_success(self, mck_val_chk, mck_extend):
        volume = self.data.test_volume
        array = self.data.array
        device_id = self.data.device_id
        new_size = self.data.test_volume.size
        ref_extra_specs = deepcopy(self.data.extra_specs_intervals_set)
        ref_extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        self.common.extend_volume(volume, new_size)
        mck_extend.assert_called_once_with(
            array, device_id, new_size, ref_extra_specs, None)

    @mock.patch.object(common.PowerMaxCommon, '_validate_rdfg_status')
    @mock.patch.object(provision.PowerMaxProvision, 'extend_volume')
    @mock.patch.object(common.PowerMaxCommon, '_array_ode_capabilities_check',
                       return_value=[True] * 4)
    @mock.patch.object(common.PowerMaxCommon, 'get_rdf_details',
                       return_value=('1', None))
    @mock.patch.object(common.PowerMaxCommon, '_extend_vol_validation_checks')
    @mock.patch.object(common.PowerMaxCommon, '_initial_setup',
                       return_value=tpd.PowerMaxData.ex_specs_rep_config)
    def test_extend_vol_rep_success_next_gen(
            self, mck_setup, mck_val_chk, mck_get_rdf, mck_ode, mck_extend,
            mck_validate):
        self.common.next_gen = True
        volume = self.data.test_volume
        array = self.data.array
        device_id = self.data.device_id
        new_size = self.data.test_volume.size
        ref_extra_specs = deepcopy(self.data.ex_specs_rep_config)
        ref_extra_specs['array'] = self.data.array

        self.common.extend_volume(volume, new_size)
        mck_extend.assert_called_once_with(
            array, device_id, new_size, ref_extra_specs, '1')
        mck_ode.assert_called_once_with(
            array, ref_extra_specs[utils.REP_CONFIG], True)
        mck_validate.assert_called_once_with(array, ref_extra_specs)

    @mock.patch.object(common.PowerMaxCommon, '_validate_rdfg_status')
    @mock.patch.object(provision.PowerMaxProvision, 'extend_volume')
    @mock.patch.object(common.PowerMaxCommon, '_extend_legacy_replicated_vol')
    @mock.patch.object(common.PowerMaxCommon, '_array_ode_capabilities_check',
                       return_value=[True, True, False, False])
    @mock.patch.object(common.PowerMaxCommon, 'get_rdf_details',
                       return_value=('1', None))
    @mock.patch.object(common.PowerMaxCommon, '_extend_vol_validation_checks')
    @mock.patch.object(common.PowerMaxCommon, '_initial_setup',
                       return_value=tpd.PowerMaxData.ex_specs_rep_config)
    def test_extend_vol_rep_success_next_gen_legacy_r2(
            self, mck_setup, mck_val_chk, mck_get_rdf, mck_ode, mck_leg_extend,
            mck_extend, mck_validate):
        self.common.next_gen = True
        self.common.rep_config = self.data.rep_config
        volume = self.data.test_volume
        array = self.data.array
        device_id = self.data.device_id
        new_size = self.data.test_volume.size
        ref_extra_specs = deepcopy(self.data.ex_specs_rep_config)
        ref_extra_specs['array'] = self.data.array

        self.common.extend_volume(volume, new_size)
        mck_leg_extend.assert_called_once_with(
            array, volume, device_id, volume.name, new_size,
            ref_extra_specs, '1')
        mck_ode.assert_called_once_with(
            array, ref_extra_specs[utils.REP_CONFIG], True)
        mck_extend.assert_not_called()
        mck_validate.assert_called_once_with(array, ref_extra_specs)

    @mock.patch.object(common.PowerMaxCommon, '_validate_rdfg_status')
    @mock.patch.object(provision.PowerMaxProvision, 'extend_volume')
    @mock.patch.object(common.PowerMaxCommon, '_extend_legacy_replicated_vol')
    @mock.patch.object(common.PowerMaxCommon, '_array_ode_capabilities_check',
                       return_value=[False, False, False, False])
    @mock.patch.object(common.PowerMaxCommon, 'get_rdf_details',
                       return_value=('1', None))
    @mock.patch.object(common.PowerMaxCommon, '_extend_vol_validation_checks')
    @mock.patch.object(common.PowerMaxCommon, '_initial_setup',
                       return_value=tpd.PowerMaxData.ex_specs_rep_config)
    def test_extend_vol_rep_success_legacy(
            self, mck_setup, mck_val_chk, mck_get_rdf, mck_ode, mck_leg_extend,
            mck_extend, mck_validate):
        self.common.rep_config = self.data.rep_config
        self.common.next_gen = False
        volume = self.data.test_volume
        array = self.data.array
        device_id = self.data.device_id
        new_size = self.data.test_volume.size
        ref_extra_specs = deepcopy(self.data.ex_specs_rep_config)
        ref_extra_specs['array'] = self.data.array

        self.common.extend_volume(volume, new_size)
        mck_leg_extend.assert_called_once_with(
            array, volume, device_id, volume.name, new_size,
            ref_extra_specs, '1')
        mck_ode.assert_called_once_with(
            array, ref_extra_specs[utils.REP_CONFIG], True)
        mck_extend.assert_not_called()
        mck_validate.assert_called_once_with(array, ref_extra_specs)

    @mock.patch.object(common.PowerMaxCommon, '_validate_rdfg_status')
    @mock.patch.object(common.PowerMaxCommon, '_array_ode_capabilities_check',
                       return_value=[False, False, False, False])
    @mock.patch.object(common.PowerMaxCommon, 'get_rdf_details',
                       return_value=('1', None))
    @mock.patch.object(common.PowerMaxCommon, '_extend_vol_validation_checks')
    @mock.patch.object(
        common.PowerMaxCommon, '_initial_setup',
        return_value=tpd.PowerMaxData.ex_specs_rep_config_no_extend)
    def test_extend_vol_rep_success_legacy_allow_extend_false(
            self, mck_setup, mck_val_chk, mck_get_rdf, mck_ode, mck_validate):
        self.common.rep_config = self.data.rep_config
        self.common.next_gen = False
        volume = self.data.test_volume
        new_size = self.data.test_volume.size
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common.extend_volume, volume, new_size)

    def test_update_volume_stats(self):
        data = self.common.update_volume_stats()
        self.assertEqual('CommonTests', data['volume_backend_name'])

    def test_update_volume_stats_no_wlp(self):
        with mock.patch.object(self.common, '_update_srp_stats',
                               return_value=('123s#SRP_1#None#None',
                                             100, 90, 90, 10)):
            data = self.common.update_volume_stats()
            self.assertEqual('CommonTests', data['volume_backend_name'])

    def test_update_srp_stats_with_wl(self):
        with mock.patch.object(self.rest, 'get_srp_by_name',
                               return_value=self.data.srp_details):
            location_info, __, __, __, __ = self.common._update_srp_stats(
                self.data.array_info_wl)
            self.assertEqual(location_info, '000197800123#SRP_1#Diamond#OLTP')

    def test_update_srp_stats_no_wl(self):
        with mock.patch.object(self.rest, 'get_srp_by_name',
                               return_value=self.data.srp_details):
            location_info, __, __, __, __ = self.common._update_srp_stats(
                self.data.array_info_no_wl)
            self.assertEqual(location_info, '000197800123#SRP_1#Diamond')

    def test_find_device_on_array_success(self):
        volume = self.data.test_volume
        extra_specs = self.data.extra_specs
        ref_device_id = self.data.device_id
        founddevice_id = self.common._find_device_on_array(volume, extra_specs)
        self.assertEqual(ref_device_id, founddevice_id)

    def test_find_device_on_array_provider_location_not_string(self):
        volume = fake_volume.fake_volume_obj(
            context='cxt', provider_location=None)
        extra_specs = self.data.extra_specs
        founddevice_id = self.common._find_device_on_array(
            volume, extra_specs)
        self.assertIsNone(founddevice_id)

    def test_find_legacy_device_on_array(self):
        volume = self.data.test_legacy_vol
        extra_specs = self.data.extra_specs
        ref_device_id = self.data.device_id
        founddevice_id = self.common._find_device_on_array(volume, extra_specs)
        self.assertEqual(ref_device_id, founddevice_id)

    def test_find_host_lun_id_attached(self):
        volume = self.data.test_volume
        extra_specs = self.data.extra_specs
        host = 'HostX'
        host_lun = (
            self.data.maskingview[0]['maskingViewConnection'][0][
                'host_lun_address'])
        ref_masked = {'hostlunid': int(host_lun, 16),
                      'maskingview': self.data.masking_view_name_f,
                      'array': self.data.array,
                      'device_id': self.data.device_id}
        maskedvols, __ = self.common.find_host_lun_id(volume, host,
                                                      extra_specs)
        self.assertEqual(ref_masked, maskedvols)

    def test_find_host_lun_id_not_attached(self):
        volume = self.data.test_volume
        extra_specs = self.data.extra_specs
        host = 'HostX'
        with mock.patch.object(self.rest, 'find_mv_connections_for_vol',
                               return_value=None):
            maskedvols, __ = self.common.find_host_lun_id(
                volume, host, extra_specs)
            self.assertEqual({}, maskedvols)

    @mock.patch.object(
        common.PowerMaxCommon, '_get_masking_views_from_volume',
        return_value=([tpd.PowerMaxData.masking_view_name_f],
                      [tpd.PowerMaxData.masking_view_name_f,
                       tpd.PowerMaxData.masking_view_name_Y_f]))
    def test_find_host_lun_id_multiattach(self, mock_mask):
        volume = self.data.test_volume
        extra_specs = self.data.extra_specs
        __, is_multiattach = self.common.find_host_lun_id(
            volume, 'HostX', extra_specs)
        self.assertTrue(is_multiattach)

    @mock.patch.object(rest.PowerMaxRest, 'get_rdf_pair_volume',
                       return_value=tpd.PowerMaxData.rdf_group_vol_details)
    @mock.patch.object(rest.PowerMaxRest, 'get_volume',
                       return_value=tpd.PowerMaxData.volume_details[0])
    def test_find_host_lun_id_rep_extra_specs(self, mock_vol, mock_tgt):
        self.common.find_host_lun_id(
            self.data.test_volume, 'HostX',
            self.data.extra_specs, self.data.rep_extra_specs)
        mock_tgt.assert_called_once()

    @mock.patch.object(rest.PowerMaxRest, 'find_mv_connections_for_vol',
                       return_value='1')
    @mock.patch.object(common.PowerMaxCommon, '_get_masking_views_from_volume',
                       side_effect=[([], ['OS-HostX-I-PG-MV']),
                                    (['OS-HostX-I-PG-MV'],
                                     ['OS-HostX-I-PG-MV'])])
    @mock.patch.object(rest.PowerMaxRest, 'get_volume',
                       return_value=tpd.PowerMaxData.volume_details[0])
    def test_find_host_lun_id_backward_compatible(
            self, mock_vol, mock_mvs, mock_mv_conns):
        expected_dict = {'hostlunid': '1', 'maskingview': 'OS-HostX-I-PG-MV',
                         'array': '000197800123', 'device_id': '00001'}
        self.common.powermax_short_host_name_template = (
            'shortHostName[:7]finance')
        masked_vols, is_multiattach = self.common.find_host_lun_id(
            self.data.test_volume, 'HostX',
            self.data.extra_specs)
        self.assertEqual(expected_dict, masked_vols)
        self.assertFalse(is_multiattach)
        mock_mv_conns.assert_called_once()

    def test_get_masking_views_from_volume(self):
        array = self.data.array
        device_id = self.data.device_id
        host = 'HostX'
        ref_mv_list = [self.data.masking_view_name_f]
        maskingview_list, __ = self.common.get_masking_views_from_volume(
            array, self.data.test_volume, device_id, host)
        self.assertEqual(ref_mv_list, maskingview_list)
        # is metro
        with mock.patch.object(self.utils, 'is_metro_device',
                               return_value=True):
            __, is_metro = self.common.get_masking_views_from_volume(
                array, self.data.test_volume, device_id, host)
            self.assertTrue(is_metro)

    def test_get_masking_views_from_volume_wrong_host(self):
        array = self.data.array
        device_id = self.data.device_id
        host = 'DifferentHost'
        maskingview_list, __ = self.common.get_masking_views_from_volume(
            array, self.data.test_volume, device_id, host)
        self.assertEqual([], maskingview_list)

    def test_find_host_lun_id_no_host_check(self):
        volume = self.data.test_volume
        extra_specs = self.data.extra_specs
        host_lun = (self.data.maskingview[0]['maskingViewConnection'][0][
            'host_lun_address'])
        ref_masked = {'hostlunid': int(host_lun, 16),
                      'maskingview': self.data.masking_view_name_f,
                      'array': self.data.array,
                      'device_id': self.data.device_id}
        maskedvols, __ = self.common.find_host_lun_id(
            volume, None, extra_specs)
        self.assertEqual(ref_masked, maskedvols)

    def test_initial_setup_success(self):
        volume = self.data.test_volume
        ref_extra_specs = deepcopy(self.data.extra_specs_intervals_set)
        ref_extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        extra_specs = self.common._initial_setup(volume)
        self.assertEqual(ref_extra_specs, extra_specs)

    def test_initial_setup_failed(self):
        volume = self.data.test_volume
        with mock.patch.object(
                self.common, 'get_attributes_from_cinder_config',
                return_value=None):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.common._initial_setup, volume)

    def test_initial_setup_success_specs_init_conn_call(self):
        volume = self.data.test_volume
        array_info = self.common.get_attributes_from_cinder_config()
        extra_specs, __ = self.common._set_config_file_and_get_extra_specs(
            volume)
        with mock.patch.object(
                self.common, '_set_vmax_extra_specs',
                side_effect=self.common._set_vmax_extra_specs) as mck_specs:
            self.common._initial_setup(volume, init_conn=True)
            mck_specs.assert_called_once_with(
                extra_specs, array_info, True)

    @mock.patch.object(rest.PowerMaxRest, 'get_rdf_pair_volume',
                       return_value=tpd.PowerMaxData.rdf_group_vol_details)
    def test_populate_masking_dict(self, mock_tgt):
        volume = self.data.test_volume
        connector = self.data.connector
        extra_specs = deepcopy(self.data.extra_specs)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        extra_specs[utils.WORKLOAD] = self.data.workload
        ref_mv_dict = self.data.masking_view_dict
        self.common.next_gen = False
        self.common.powermax_port_group_name_template = 'portGroupName'
        extra_specs.pop(utils.IS_RE, None)
        masking_view_dict = self.common._populate_masking_dict(
            volume, connector, extra_specs)
        self.assertEqual(ref_mv_dict, masking_view_dict)
        # Metro volume, pass in rep_extra_specs and retrieve target device
        rep_extra_specs = deepcopy(self.data.rep_extra_specs)
        rep_extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        self.common._populate_masking_dict(
            volume, connector, extra_specs, rep_extra_specs)
        mock_tgt.assert_called_once()
        # device_id is None
        with mock.patch.object(self.common, '_find_device_on_array',
                               return_value=None):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.common._populate_masking_dict,
                              volume, connector, extra_specs)

    def test_populate_masking_dict_no_slo(self):
        volume = self.data.test_volume
        connector = self.data.connector
        extra_specs = {'slo': None, 'workload': None, 'srp': self.data.srp,
                       'array': self.data.array,
                       utils.PORTGROUPNAME: self.data.port_group_name_f}
        ref_mv_dict = self.data.masking_view_dict_no_slo
        masking_view_dict = self.common._populate_masking_dict(
            volume, connector, extra_specs)
        self.assertEqual(ref_mv_dict, masking_view_dict)

    def test_populate_masking_dict_compr_disabled(self):
        volume = self.data.test_volume
        connector = self.data.connector
        extra_specs = deepcopy(self.data.extra_specs)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        extra_specs[utils.DISABLECOMPRESSION] = "true"
        ref_mv_dict = self.data.masking_view_dict_compression_disabled
        extra_specs[utils.WORKLOAD] = self.data.workload
        masking_view_dict = self.common._populate_masking_dict(
            volume, connector, extra_specs)
        self.assertEqual(ref_mv_dict, masking_view_dict)

    def test_populate_masking_dict_next_gen(self):
        volume = self.data.test_volume
        connector = self.data.connector
        extra_specs = deepcopy(self.data.extra_specs)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        self.common.next_gen = True
        masking_view_dict = self.common._populate_masking_dict(
            volume, connector, extra_specs)
        self.assertEqual('NONE', masking_view_dict[utils.WORKLOAD])

    @mock.patch.object(common.PowerMaxCommon, '_cleanup_device_snapvx')
    def test_create_cloned_volume(self, mck_cleanup_snaps):
        volume = self.data.test_clone_volume
        source_volume = self.data.test_volume
        extra_specs = self.data.extra_specs
        ref_response = (self.data.provider_location_clone, dict(), dict())
        clone_dict, rep_update, rep_info_dict = (
            self.common._create_cloned_volume(
                volume, source_volume, extra_specs))
        self.assertEqual(ref_response, (clone_dict, rep_update, rep_info_dict))

    @mock.patch.object(common.PowerMaxCommon, '_cleanup_device_snapvx')
    def test_create_cloned_volume_is_snapshot(self, mck_cleanup_snaps):
        volume = self.data.test_snapshot
        source_volume = self.data.test_volume
        extra_specs = self.data.extra_specs
        ref_response = (self.data.snap_location, dict(), dict())
        clone_dict, rep_update, rep_info_dict = (
            self.common._create_cloned_volume(
                volume, source_volume, extra_specs, True, False))
        self.assertEqual(ref_response, (clone_dict, rep_update, rep_info_dict))

    @mock.patch.object(common.PowerMaxCommon, '_cleanup_device_snapvx')
    def test_create_cloned_volume_from_snapshot(self, mck_cleanup_snaps):
        volume = self.data.test_clone_volume
        source_volume = self.data.test_snapshot
        extra_specs = self.data.extra_specs
        ref_response = (self.data.provider_location_snapshot, dict(), dict())
        clone_dict, rep_update, rep_info_dict = (
            self.common._create_cloned_volume(
                volume, source_volume, extra_specs, False, True))
        self.assertEqual(ref_response, (clone_dict, rep_update, rep_info_dict))

    def test_create_cloned_volume_not_licenced(self):
        volume = self.data.test_clone_volume
        source_volume = self.data.test_volume
        extra_specs = self.data.extra_specs
        with mock.patch.object(self.rest, 'is_snapvx_licensed',
                               return_value=False):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.common._create_cloned_volume,
                              volume, source_volume, extra_specs)

    @mock.patch.object(common.PowerMaxCommon,
                       '_find_device_on_array')
    def test_create_cloned_volume_not_licenced_2(self, mock_device):
        volume = self.data.test_clone_volume
        source_volume = self.data.test_volume
        extra_specs = self.data.extra_specs
        with mock.patch.object(self.rest, 'is_snapvx_licensed',
                               return_value=False):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.common._create_cloned_volume,
                              volume, source_volume, extra_specs,
                              False, False)
            mock_device.assert_not_called()

    @mock.patch.object(common.PowerMaxCommon,
                       '_find_device_on_array',
                       return_value=None)
    @mock.patch.object(common.PowerMaxCommon,
                       '_cleanup_device_snapvx')
    def test_create_cloned_volume_source_not_found(
            self, mock_check, mock_device):
        volume = self.data.test_clone_volume
        source_volume = self.data.test_volume
        extra_specs = self.data.extra_specs
        with mock.patch.object(self.rest, 'is_snapvx_licensed',
                               return_value=True):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.common._create_cloned_volume,
                              volume, source_volume, extra_specs,
                              False, False)
            mock_check.assert_not_called()

    def test_parse_snap_info_found(self):
        ref_device_id = self.data.device_id
        ref_snap_name = self.data.snap_location['snap_name']
        sourcedevice_id, foundsnap_name, __ = self.common._parse_snap_info(
            self.data.array, self.data.test_snapshot)
        self.assertEqual(ref_device_id, sourcedevice_id)
        self.assertEqual(ref_snap_name, foundsnap_name)

    def test_parse_snap_info_not_found(self):
        ref_snap_name = None
        with mock.patch.object(self.rest, 'get_volume_snap',
                               return_value=None):
            __, foundsnap_name, __ = self.common._parse_snap_info(
                self.data.array, self.data.test_snapshot)
            self.assertIsNone(ref_snap_name, foundsnap_name)

    def test_parse_snap_info_exception(self):
        with mock.patch.object(
                self.rest, 'get_volume_snaps',
                side_effect=exception.VolumeBackendAPIException):
            __, foundsnap_name, __ = self.common._parse_snap_info(
                self.data.array, self.data.test_snapshot)
            self.assertIsNone(foundsnap_name)

    def test_parse_snap_info_provider_location_not_string(self):
        snapshot = fake_snapshot.fake_snapshot_obj(
            context='ctxt', provider_loaction={'not': 'string'})
        sourcedevice_id, foundsnap_name, __ = self.common._parse_snap_info(
            self.data.array, snapshot)
        self.assertIsNone(foundsnap_name)

    def test_create_snapshot_success(self):
        array = self.data.array
        snapshot = self.data.test_snapshot
        source_device_id = self.data.device_id
        extra_specs = self.data.extra_specs
        ref_dict = {'snap_name': self.data.test_snapshot_snap_name,
                    'source_id': self.data.device_id}
        snap_dict = self.common._create_snapshot(
            array, snapshot, source_device_id, extra_specs)
        self.assertEqual(ref_dict, snap_dict)

    def test_create_snapshot_exception(self):
        array = self.data.array
        snapshot = self.data.test_snapshot
        source_device_id = self.data.device_id
        extra_specs = self.data.extra_specs
        with mock.patch.object(
                self.provision, 'create_volume_snapvx',
                side_effect=exception.VolumeBackendAPIException):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.common._create_snapshot,
                              array, snapshot, source_device_id, extra_specs)

    @mock.patch.object(rest.PowerMaxRest, 'get_volume_snapshot_list',
                       return_value=list())
    @mock.patch.object(masking.PowerMaxMasking,
                       'remove_vol_from_storage_group')
    def test_delete_volume_from_srp(self, mock_rm, mock_get_snaps):
        array = self.data.array
        device_id = self.data.device_id
        volume_name = self.data.test_volume.name
        ref_extra_specs = deepcopy(self.data.extra_specs_intervals_set)
        ref_extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        volume = self.data.test_volume
        with mock.patch.object(self.common, '_cleanup_device_snapvx'):
            with mock.patch.object(
                    self.common, '_delete_from_srp') as mock_delete:
                self.common._delete_volume(volume)
                mock_delete.assert_called_once_with(
                    array, device_id, volume_name, ref_extra_specs)

    def test_delete_volume_not_found(self):
        volume = self.data.test_volume
        with mock.patch.object(self.common, '_find_device_on_array',
                               return_value=None):
            with mock.patch.object(
                    self.common, '_delete_from_srp') as mock_delete:
                self.common._delete_volume(volume)
                mock_delete.assert_not_called()

    def test_create_volume_success(self):
        volume = self.data.test_volume
        volume_name = '1'
        volume_size = self.data.test_volume.size
        extra_specs = self.data.extra_specs
        ref_response = (self.data.provider_location, dict(), dict())
        with mock.patch.object(self.rest, 'get_volume',
                               return_value=self.data.volume_details[0]):
            volume_dict, rep_update, rep_info_dict = (
                self.common._create_volume(
                    volume, volume_name, volume_size, extra_specs))
        self.assertEqual(ref_response,
                         (volume_dict, rep_update, rep_info_dict))

    @mock.patch.object(rest.PowerMaxRest, 'find_volume_device_id',
                       return_value=tpd.PowerMaxData.device_id2)
    @mock.patch.object(
        common.PowerMaxCommon, '_create_non_replicated_volume',
        return_value=deepcopy(tpd.PowerMaxData.provider_location))
    @mock.patch.object(rest.PowerMaxRest, 'get_volume',
                       return_value=tpd.PowerMaxData.volume_details[0])
    def test_create_volume_update_returning_device_id(
            self, mck_get, mck_create, mck_find):
        volume = self.data.test_volume
        volume_name = '1'
        volume_size = self.data.test_volume.size
        extra_specs = self.data.extra_specs
        ref_response = (self.data.provider_location2, dict(), dict())
        volume_dict, rep_update, rep_info_dict = (
            self.common._create_volume(
                volume, volume_name, volume_size, extra_specs))
        self.assertEqual(ref_response,
                         (volume_dict, rep_update, rep_info_dict))

    def test_create_volume_success_next_gen(self):
        volume = self.data.test_volume
        volume_name = '1'
        volume_size = self.data.test_volume.size
        extra_specs = self.data.extra_specs
        self.common.next_gen = True
        with mock.patch.object(
                self.utils, 'is_compression_disabled', return_value=True):
            with mock.patch.object(
                    self.rest, 'get_array_model_info',
                    return_value=('PowerMax 2000', True)):
                with mock.patch.object(
                        self.masking,
                        'get_or_create_default_storage_group') as mock_get:
                    self.common._create_volume(
                        volume, volume_name, volume_size, extra_specs)
                    mock_get.assert_called_once_with(
                        extra_specs['array'], extra_specs[utils.SRP],
                        extra_specs[utils.SLO], 'NONE', extra_specs, True,
                        False, None)

    @mock.patch.object(provision.PowerMaxProvision, 'create_volume_from_sg',
                       side_effect=exception.VolumeBackendAPIException(''))
    @mock.patch.object(common.PowerMaxCommon,
                       '_cleanup_non_rdf_volume_create_post_failure')
    @mock.patch.object(rest.PowerMaxRest, 'delete_storage_group')
    def test_create_volume_failed(self, mck_del, mck_cleanup, mck_create):
        volume = self.data.test_volume
        volume_name = self.data.test_volume.name
        volume_size = self.data.test_volume.size
        extra_specs = self.data.extra_specs
        dev1 = self.data.device_id
        dev2 = self.data.device_id2
        with mock.patch.object(
                self.rest, 'get_volumes_in_storage_group',
                side_effect=[[dev1], [dev1, dev2]]):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.common._create_volume,
                              volume, volume_name, volume_size,
                              extra_specs)
            mck_cleanup.assert_called_once_with(
                volume, volume_name, extra_specs, [dev2])
        # path 2: no new volumes created
        with mock.patch.object(
                self.rest, 'get_volumes_in_storage_group',
                side_effect=[[], []]):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.common._create_volume,
                              volume, volume_name, volume_size,
                              extra_specs)
            mck_del.assert_called_once()

    @mock.patch.object(common.PowerMaxCommon, 'cleanup_rdf_device_pair')
    @mock.patch.object(
        rest.PowerMaxRest, 'is_vol_in_rep_session', return_value=('', '', [
            {utils.RDF_GROUP_NO: tpd.PowerMaxData.rdf_group_no_1}]))
    @mock.patch.object(rest.PowerMaxRest, 'srdf_resume_replication')
    @mock.patch.object(utils.PowerMaxUtils, 'get_default_storage_group_name',
                       return_value=tpd.PowerMaxData.storagegroup_name_f)
    @mock.patch.object(common.PowerMaxCommon, 'prepare_replication_details',
                       return_value=('', tpd.PowerMaxData.rep_extra_specs,
                                     '', '',))
    def test_cleanup_rdf_volume_create_post_failure_sync(
            self, mck_prep, mck_sg, mck_resume, mck_sess, mck_clean):
        array = self.data.array
        volume = self.data.test_volume
        volume_name = self.data.test_volume.name
        extra_specs = deepcopy(self.data.extra_specs_rep_enabled)
        extra_specs[utils.REP_CONFIG] = self.data.rep_config_sync
        extra_specs['rep_mode'] = utils.REP_SYNC
        devices = [self.data.device_id]
        self.common._cleanup_rdf_volume_create_post_failure(
            volume, volume_name, extra_specs, devices)
        mck_prep.assert_called_once_with(extra_specs)
        mck_sg.assert_called_once_with(
            extra_specs['srp'], extra_specs['slo'], extra_specs['workload'],
            False, True, extra_specs['rep_mode'])
        mck_resume.assert_called_once_with(
            array, self.data.storagegroup_name_f, self.data.rdf_group_no_1,
            self.data.rep_extra_specs)
        mck_sess.assert_called_once_with(array, self.data.device_id)
        mck_clean.assert_called_once_with(
            array, self.data.rdf_group_no_1, self.data.device_id, extra_specs)

    @mock.patch.object(common.PowerMaxCommon, 'cleanup_rdf_device_pair')
    @mock.patch.object(
        rest.PowerMaxRest, 'is_vol_in_rep_session', return_value=('', '', [
            {utils.RDF_GROUP_NO: tpd.PowerMaxData.rdf_group_no_1}]))
    @mock.patch.object(rest.PowerMaxRest, 'srdf_resume_replication')
    @mock.patch.object(utils.PowerMaxUtils, 'get_rdf_management_group_name',
                       return_value=tpd.PowerMaxData.storagegroup_name_f)
    @mock.patch.object(common.PowerMaxCommon, 'prepare_replication_details',
                       return_value=('', tpd.PowerMaxData.rep_extra_specs,
                                     '', '',))
    def test_cleanup_rdf_volume_create_post_failure_non_sync(
            self, mck_prep, mck_mgmt, mck_resume, mck_sess, mck_clean):
        array = self.data.array
        volume = self.data.test_volume
        volume_name = self.data.test_volume.name
        extra_specs = deepcopy(self.data.extra_specs_rep_enabled)
        extra_specs[utils.REP_CONFIG] = self.data.rep_config_async
        extra_specs['rep_mode'] = utils.REP_ASYNC
        devices = [self.data.device_id]
        self.common._cleanup_rdf_volume_create_post_failure(
            volume, volume_name, extra_specs, devices)
        mck_prep.assert_called_once_with(extra_specs)
        mck_mgmt.assert_called_once_with(extra_specs[utils.REP_CONFIG])
        mck_resume.assert_called_once_with(
            array, self.data.storagegroup_name_f, self.data.rdf_group_no_1,
            self.data.rep_extra_specs)
        mck_sess.assert_called_once_with(array, self.data.device_id)
        mck_clean.assert_called_once_with(
            array, self.data.rdf_group_no_1, self.data.device_id, extra_specs)

    @mock.patch.object(common.PowerMaxCommon, '_delete_from_srp')
    @mock.patch.object(masking.PowerMaxMasking, 'remove_and_reset_members')
    @mock.patch.object(rest.PowerMaxRest, 'is_vol_in_rep_session',
                       return_value=('', '', False))
    @mock.patch.object(rest.PowerMaxRest, 'srdf_resume_replication')
    @mock.patch.object(utils.PowerMaxUtils, 'get_rdf_management_group_name',
                       return_value=tpd.PowerMaxData.storagegroup_name_f)
    @mock.patch.object(common.PowerMaxCommon, 'prepare_replication_details',
                       return_value=('', tpd.PowerMaxData.rep_extra_specs,
                                     '', '',))
    def test_cleanup_rdf_volume_create_post_failure_pre_rdf_establish(
            self, mck_prep, mck_mgmt, mck_resume, mck_sess, mck_rem, mck_del):
        array = self.data.array
        volume = self.data.test_volume
        volume_name = self.data.test_volume.name
        extra_specs = deepcopy(self.data.extra_specs_rep_enabled)
        extra_specs[utils.REP_CONFIG] = self.data.rep_config_sync
        extra_specs['rep_mode'] = utils.REP_ASYNC
        devices = [self.data.device_id]
        self.common._cleanup_rdf_volume_create_post_failure(
            volume, volume_name, extra_specs, devices)
        mck_prep.assert_called_once_with(extra_specs)
        mck_mgmt.assert_called_once_with(extra_specs[utils.REP_CONFIG])
        mck_resume.assert_called_once_with(
            array, self.data.storagegroup_name_f, self.data.rdf_group_no_1,
            self.data.rep_extra_specs)
        mck_sess.assert_called_once_with(array, self.data.device_id)
        mck_rem.assert_called_once_with(array, volume, self.data.device_id,
                                        volume_name, extra_specs, False)
        mck_del.assert_called_once_with(array, self.data.device_id,
                                        volume_name, extra_specs)

    @mock.patch.object(common.PowerMaxCommon, '_delete_from_srp')
    @mock.patch.object(masking.PowerMaxMasking, 'remove_and_reset_members')
    def test_cleanup_non_rdf_volume_create_post_failure(
            self, mck_remove, mck_del):
        array = self.data.array
        volume = self.data.test_volume
        volume_name = self.data.test_volume.name
        extra_specs = self.data.extra_specs
        devices = [self.data.device_id]
        self.common._cleanup_non_rdf_volume_create_post_failure(
            volume, volume_name, extra_specs, devices)
        mck_remove.assert_called_once_with(
            array, volume, self.data.device_id, volume_name, extra_specs,
            False)
        mck_del.assert_called_once_with(
            array, self.data.device_id, volume_name, extra_specs)

    def test_create_volume_incorrect_slo(self):
        volume = self.data.test_volume
        volume_name = self.data.test_volume.name
        volume_size = self.data.test_volume.size
        extra_specs = {'slo': 'Diamondz',
                       'workload': 'DSSSS',
                       'srp': self.data.srp,
                       'array': self.data.array}
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.common._create_volume,
            volume, volume_name, volume_size, extra_specs)

    def test_set_vmax_extra_specs(self):
        srp_record = self.common.get_attributes_from_cinder_config()
        extra_specs = self.common._set_vmax_extra_specs(
            self.data.vol_type_extra_specs, srp_record)
        ref_extra_specs = deepcopy(self.data.extra_specs_intervals_set)
        ref_extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        self.assertEqual(ref_extra_specs, extra_specs)

    def test_set_vmax_extra_specs_no_srp_name(self):
        srp_record = self.common.get_attributes_from_cinder_config()
        with mock.patch.object(self.rest, 'get_slo_list',
                               return_value=[]):
            extra_specs = self.common._set_vmax_extra_specs({}, srp_record)
            self.assertIsNone(extra_specs['slo'])

    def test_set_vmax_extra_specs_compr_disabled(self):
        with mock.patch.object(self.rest, 'is_compression_capable',
                               return_value=True):
            srp_record = self.common.get_attributes_from_cinder_config()
            extra_specs = self.common._set_vmax_extra_specs(
                self.data.vol_type_extra_specs_compr_disabled, srp_record)
            ref_extra_specs = deepcopy(self.data.extra_specs_intervals_set)
            ref_extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
            ref_extra_specs[utils.DISABLECOMPRESSION] = "true"
            self.assertEqual(ref_extra_specs, extra_specs)

    def test_set_vmax_extra_specs_compr_disabled_not_compr_capable(self):
        srp_record = self.common.get_attributes_from_cinder_config()
        extra_specs = self.common._set_vmax_extra_specs(
            self.data.vol_type_extra_specs_compr_disabled, srp_record)
        ref_extra_specs = deepcopy(self.data.extra_specs_intervals_set)
        ref_extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        self.assertEqual(ref_extra_specs, extra_specs)

    def test_set_vmax_extra_specs_portgroup_as_spec(self):
        srp_record = self.common.get_attributes_from_cinder_config()
        extra_specs = self.common._set_vmax_extra_specs(
            {utils.PORTGROUPNAME: 'extra_spec_pg'}, srp_record)
        self.assertEqual('extra_spec_pg', extra_specs[utils.PORTGROUPNAME])

    def test_set_vmax_extra_specs_no_portgroup_set(self):
        srp_record = {
            'srpName': 'SRP_1', 'RestServerIp': '1.1.1.1',
            'RestPassword': 'smc', 'SSLCert': None, 'RestServerPort': 8443,
            'SSLVerify': False, 'RestUserName': 'smc',
            'SerialNumber': '000197800123'}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common._set_vmax_extra_specs,
                          {}, srp_record)

    def test_set_vmax_extra_specs_next_gen(self):
        srp_record = self.common.get_attributes_from_cinder_config()
        self.common.next_gen = True
        extra_specs = self.common._set_vmax_extra_specs(
            self.data.vol_type_extra_specs, srp_record)
        ref_extra_specs = deepcopy(self.data.extra_specs_intervals_set)
        ref_extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        self.assertEqual('NONE', extra_specs[utils.WORKLOAD])

    def test_set_vmax_extra_specs_tags_not_set(self):
        srp_record = self.common.get_attributes_from_cinder_config()
        extra_specs = self.common._set_vmax_extra_specs(
            self.data.vol_type_extra_specs, srp_record)
        self.assertNotIn('storagetype:storagegrouptags', extra_specs)

    def test_set_vmax_extra_specs_tags_set_correctly(self):
        srp_record = self.common.get_attributes_from_cinder_config()
        extra_specs = self.common._set_vmax_extra_specs(
            self.data.vol_type_extra_specs_tags, srp_record)
        self.assertEqual(
            self.data.vol_type_extra_specs_tags[utils.STORAGE_GROUP_TAGS],
            extra_specs[utils.STORAGE_GROUP_TAGS])

    def test_set_vmax_extra_specs_tags_set_incorrectly(self):
        srp_record = self.common.get_attributes_from_cinder_config()
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common._set_vmax_extra_specs,
                          self.data.vol_type_extra_specs_tags_bad, srp_record)

    def test_set_vmax_extra_specs_pg_specs_init_conn(self):
        pool_record = self.common.get_attributes_from_cinder_config()
        with mock.patch.object(
                self.common, '_select_port_group_for_extra_specs',
                side_effect=(
                    self.common._select_port_group_for_extra_specs)) as mck_s:
            self.common._set_vmax_extra_specs(
                self.data.vol_type_extra_specs, pool_record, init_conn=True)
            mck_s.assert_called_once_with(
                self.data.vol_type_extra_specs, pool_record, True)

    def test_raise_exception_if_array_not_configured(self):
        self.driver.configuration.powermax_array = None
        self.assertRaises(exception.InvalidConfigurationValue,
                          self.common.get_attributes_from_cinder_config)

    def test_raise_exception_if_srp_not_configured(self):
        self.driver.configuration.powermax_srp = None
        self.assertRaises(exception.InvalidConfigurationValue,
                          self.common.get_attributes_from_cinder_config)

    def test_delete_volume_from_srp_success(self):
        array = self.data.array
        device_id = self.data.device_id
        volume_name = self.data.test_volume.name
        extra_specs = self.data.extra_specs
        with mock.patch.object(
                self.provision, 'delete_volume_from_srp') as mock_del:
            self.common._delete_from_srp(array, device_id, volume_name,
                                         extra_specs)
            mock_del.assert_called_once_with(array, device_id, volume_name)

    def test_delete_volume_from_srp_failed(self):
        self.mock_object(time, 'sleep')
        array = self.data.array
        device_id = self.data.failed_resource
        volume_name = self.data.test_volume.name
        extra_specs = self.data.extra_specs
        with mock.patch.object(
                self.masking,
                'add_volume_to_default_storage_group') as mock_add:
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.common._delete_from_srp, array,
                              device_id, volume_name, extra_specs)
            mock_add.assert_not_called()

    @mock.patch.object(utils.PowerMaxUtils, 'is_volume_failed_over',
                       side_effect=[True, False])
    @mock.patch.object(common.PowerMaxCommon, '_get_replication_extra_specs',
                       return_value=tpd.PowerMaxData.rep_extra_specs)
    def test_get_target_wwns_from_masking_view(self, mock_rep_specs, mock_fo):
        ref_wwns = [self.data.wwnn1]
        for x in range(0, 2):
            target_wwns = self.common._get_target_wwns_from_masking_view(
                self.data.device_id, self.data.connector['host'],
                self.data.extra_specs)
            self.assertEqual(ref_wwns, target_wwns)

    def test_get_target_wwns_from_masking_view_no_mv(self):
        with mock.patch.object(self.common, '_get_masking_views_from_volume',
                               return_value=([], None)):
            target_wwns = self.common._get_target_wwns_from_masking_view(
                self.data.device_id, self.data.connector['host'],
                self.data.extra_specs)
            self.assertEqual([], target_wwns)

    @mock.patch.object(common.PowerMaxCommon, '_get_replication_extra_specs',
                       return_value=tpd.PowerMaxData.rep_extra_specs)
    @mock.patch.object(common.PowerMaxCommon, 'get_rdf_details',
                       return_value=('1', tpd.PowerMaxData.remote_array))
    @mock.patch.object(rest.PowerMaxRest, 'get_rdf_pair_volume',
                       return_value=tpd.PowerMaxData.rdf_group_vol_details)
    @mock.patch.object(
        common.PowerMaxCommon, '_get_target_wwns_from_masking_view',
        return_value=[tpd.PowerMaxData.wwnn1])
    def test_get_target_wwns(
            self, mck_wwns, mock_tgt, mock_rdf_grp, mock_specs):
        __, metro_wwns = self.common.get_target_wwns_from_masking_view(
            self.data.test_volume, self.data.connector)
        self.assertEqual([], metro_wwns)
        # Is metro volume
        with mock.patch.object(common.PowerMaxCommon, '_initial_setup',
                               return_value=self.data.ex_specs_rep_config):
            __, metro_wwns = self.common.get_target_wwns_from_masking_view(
                self.data.test_volume, self.data.connector)
            self.assertEqual([self.data.wwnn1], metro_wwns)

    @mock.patch.object(common.PowerMaxCommon,
                       '_get_target_wwns_from_masking_view')
    @mock.patch.object(utils.PowerMaxUtils, 'get_host_name_label',
                       return_value = 'my_short_h94485')
    @mock.patch.object(utils.PowerMaxUtils, 'is_replication_enabled',
                       return_value=False)
    def test_get_target_wwns_host_override(
            self, mock_rep_check, mock_label, mock_mv):
        host_record = {'host': 'my_short_host_name'}
        connector = deepcopy(self.data.connector)
        connector.update(host_record)
        extra_specs = {'pool_name': 'Diamond+DSS+SRP_1+000197800123',
                       'srp': 'SRP_1', 'array': '000197800123',
                       'storagetype:portgroupname': 'OS-fibre-PG',
                       'interval': 1, 'retries': 1, 'slo': 'Diamond',
                       'workload': 'DSS'}
        host_template = 'shortHostName[:10]uuid[:5]'
        self.common.powermax_short_host_name_template = host_template
        self.common.get_target_wwns_from_masking_view(
            self.data.test_volume, connector)
        mock_label.assert_called_once_with(
            connector['host'], host_template)
        mock_mv.assert_called_once_with(
            self.data.device_id, 'my_short_h94485', extra_specs)

    def test_get_port_group_from_masking_view(self):
        array = self.data.array
        maskingview_name = self.data.masking_view_name_f

        with mock.patch.object(self.rest,
                               'get_element_from_masking_view') as mock_get:
            self.common.get_port_group_from_masking_view(
                array, maskingview_name)
            mock_get.assert_called_once_with(
                array, maskingview_name, portgroup=True)

    def test_get_initiator_group_from_masking_view(self):
        array = self.data.array
        maskingview_name = self.data.masking_view_name_f
        with mock.patch.object(
                self.rest, 'get_element_from_masking_view') as mock_get:
            self.common.get_initiator_group_from_masking_view(
                array, maskingview_name)
            mock_get.assert_called_once_with(
                array, maskingview_name, host=True)

    def test_get_common_masking_views(self):
        array = self.data.array
        portgroup_name = self.data.port_group_name_f
        initiator_group_name = self.data.initiatorgroup_name_f
        with mock.patch.object(
                self.rest, 'get_common_masking_views') as mock_get:
            self.common.get_common_masking_views(
                array, portgroup_name, initiator_group_name)
            mock_get.assert_called_once_with(
                array, portgroup_name, initiator_group_name)

    def test_get_iscsi_ip_iqn_port(self):
        phys_port = '%(dir)s:%(port)s' % {'dir': self.data.iscsi_dir,
                                          'port': self.data.iscsi_port}
        ref_ip_iqn = [{'iqn': self.data.initiator,
                       'ip': self.data.ip,
                       'physical_port': phys_port}]

        director = self.data.portgroup[1]['symmetrixPortKey'][0]['directorId']
        port = self.data.portgroup[1]['symmetrixPortKey'][0]['portId']
        dirport = "%s:%s" % (director, port)

        ip_iqn_list = self.common._get_iscsi_ip_iqn_port(self.data.array,
                                                         dirport)
        self.assertEqual(ref_ip_iqn, ip_iqn_list)

    def test_find_ip_and_iqns(self):
        ref_ip_iqn = [{'iqn': self.data.initiator,
                       'ip': self.data.ip,
                       'physical_port': self.data.iscsi_dir_port}]
        ip_iqn_list = self.common._find_ip_and_iqns(
            self.data.array, self.data.port_group_name_i)
        self.assertEqual(ref_ip_iqn, ip_iqn_list)

    @mock.patch.object(rest.PowerMaxRest, 'get_portgroup',
                       return_value=None)
    def test_find_ip_and_iqns_no_port_group(self, mock_port):
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.common._find_ip_and_iqns, self.data.array,
            self.data.port_group_name_i)

    def test_create_replica_snap_name(self):
        array = self.data.array
        clone_volume = self.data.test_clone_volume
        source_device_id = self.data.device_id
        snap_name = self.data.snap_location['snap_name']
        ref_response = (self.data.provider_location_snapshot, dict(), dict())
        clone_dict, rep_update, rep_info_dict = self.common._create_replica(
            array, clone_volume, source_device_id,
            self.data.extra_specs, snap_name)
        self.assertEqual(ref_response, (clone_dict, rep_update, rep_info_dict))

    @mock.patch.object(
        rest.PowerMaxRest, 'get_slo_list', return_value=['Diamond'])
    @mock.patch.object(
        common.PowerMaxCommon, '_create_volume',
        return_value=(tpd.PowerMaxData.rep_info_dict,
                      tpd.PowerMaxData.replication_update,
                      tpd.PowerMaxData.rep_info_dict))
    @mock.patch.object(rest.PowerMaxRest, 'rdf_resume_with_retries')
    @mock.patch.object(rest.PowerMaxRest, 'srdf_suspend_replication')
    @mock.patch.object(rest.PowerMaxRest, 'wait_for_rdf_pair_sync')
    def test_create_replica_rep_enabled(
            self, mck_wait, mck_susp, mck_res, mck_create, mck_slo):
        array = self.data.array
        clone_volume = self.data.test_clone_volume
        source_device_id = self.data.device_id
        snap_name = self.data.snap_location['snap_name']
        extra_specs = deepcopy(self.data.rep_extra_specs_rep_config)
        __, rep_extra_specs, __, __ = self.common.prepare_replication_details(
            extra_specs)
        rdfg = extra_specs['rdf_group_no']
        self.common._create_replica(
            array, clone_volume, source_device_id, rep_extra_specs, snap_name)
        mck_wait.assert_called_once_with(
            array, rdfg, source_device_id, rep_extra_specs)
        mck_susp.assert_called_once_with(
            array, rep_extra_specs['sg_name'], rdfg, rep_extra_specs)
        mck_res.assert_called_once_with(array, rep_extra_specs)

    def test_create_replica_no_snap_name(self):
        array = self.data.array
        clone_volume = self.data.test_clone_volume
        source_device_id = self.data.device_id
        snap_name = "temp-" + source_device_id + "-snapshot_for_clone"
        ref_response = (self.data.provider_location_clone, dict(), dict())
        with mock.patch.object(
                self.utils, 'get_temp_snap_name',
                return_value=snap_name) as mock_get_snap:
            clone_dict, rep_update, rep_info_dict = (
                self.common._create_replica(
                    array, clone_volume, source_device_id,
                    self.data.extra_specs))
            self.assertEqual(ref_response,
                             (clone_dict, rep_update, rep_info_dict))
            mock_get_snap.assert_called_once_with(source_device_id)

    def test_create_replica_failed_cleanup_target(self):
        array = self.data.array
        clone_volume = self.data.test_clone_volume
        device_id = self.data.device_id
        snap_name = self.data.failed_resource
        clone_name = 'OS-' + clone_volume.id
        extra_specs = self.data.extra_specs
        with mock.patch.object(
                self.common, '_cleanup_target') as mock_cleanup:
            self.assertRaises(
                exception.VolumeBackendAPIException,
                self.common._create_replica, array, clone_volume, device_id,
                self.data.extra_specs, snap_name)
            mock_cleanup.assert_called_once_with(
                array, device_id, device_id, clone_name, snap_name,
                extra_specs, target_volume=clone_volume)

    def test_create_replica_failed_no_target(self):
        array = self.data.array
        clone_volume = self.data.test_clone_volume
        source_device_id = self.data.device_id
        snap_name = self.data.failed_resource
        with mock.patch.object(self.common, '_create_volume',
                               return_value=({'device_id': None}, {}, {})):
            with mock.patch.object(
                    self.common, '_cleanup_target') as mock_cleanup:
                self.assertRaises(
                    exception.VolumeBackendAPIException,
                    self.common._create_replica, array, clone_volume,
                    source_device_id, self.data.extra_specs, snap_name)
                mock_cleanup.assert_not_called()

    @mock.patch.object(
        utils.PowerMaxUtils,
        'compare_cylinders',
        side_effect=exception.VolumeBackendAPIException)
    def test_create_replica_cylinder_mismatch(self, mock_cyl):
        array = self.data.array
        clone_volume = self.data.test_clone_volume
        source_device_id = self.data.device_id
        snap_name = self.data.snap_location['snap_name']
        clone_name = 'OS-' + clone_volume.id
        with mock.patch.object(
                self.common, '_cleanup_target') as mock_cleanup:
            self.assertRaises(                     # noqa: H202
                Exception, self.common._create_replica, array,
                clone_volume, source_device_id,
                self.data.extra_specs, snap_name)  # noqa: ignore=H202
            mock_cleanup.assert_called_once_with(
                array, source_device_id, source_device_id,
                clone_name, snap_name, self.data.extra_specs,
                target_volume=clone_volume)

    @mock.patch.object(rest.PowerMaxRest, 'get_snap_id',
                       return_value=tpd.PowerMaxData.snap_id)
    @mock.patch.object(
        masking.PowerMaxMasking,
        'remove_and_reset_members')
    def test_cleanup_target_sync_present(self, mock_remove, mock_snaps):
        array = self.data.array
        clone_volume = self.data.test_clone_volume
        source_device_id = self.data.device_id
        target_device_id = self.data.device_id2
        snap_name = self.data.failed_resource
        clone_name = clone_volume.name
        extra_specs = self.data.extra_specs
        with mock.patch.object(self.rest, 'get_sync_session',
                               return_value='session'):
            with mock.patch.object(
                    self.provision, 'unlink_snapvx_tgt_volume') as mock_break:
                self.common._cleanup_target(
                    array, target_device_id, source_device_id,
                    clone_name, snap_name, extra_specs)
                mock_break.assert_called_with(
                    array, target_device_id, source_device_id,
                    snap_name, extra_specs, self.data.snap_id)

    @mock.patch.object(rest.PowerMaxRest, 'get_volume_snaps',
                       return_value=[{'snap_name': 'snap_name',
                                      'snap_id': tpd.PowerMaxData.snap_id}])
    @mock.patch.object(masking.PowerMaxMasking, 'remove_volume_from_sg')
    def test_cleanup_target_no_sync(self, mock_remove, mock_snaps):
        array = self.data.array
        clone_volume = self.data.test_clone_volume
        source_device_id = self.data.device_id
        target_device_id = self.data.device_id2
        snap_name = self.data.failed_resource
        clone_name = clone_volume.name
        extra_specs = self.data.extra_specs
        with mock.patch.object(self.rest, 'get_sync_session',
                               return_value=None):
            with mock.patch.object(
                    self.common, '_delete_from_srp') as mock_delete:
                self.common._cleanup_target(
                    array, target_device_id, source_device_id,
                    clone_name, snap_name, extra_specs)
                mock_delete.assert_called_once_with(
                    array, target_device_id, clone_name,
                    extra_specs)

    @mock.patch.object(
        common.PowerMaxCommon, 'get_volume_metadata',
        return_value={'device-meta-key-1': 'device-meta-value-1',
                      'device-meta-key-2': 'device-meta-value-2'})
    def test_manage_existing_success(self, mck_meta):
        external_ref = {u'source-name': u'00002'}
        provider_location = {'device_id': u'00002', 'array': u'000197800123'}
        ref_update = {'provider_location': six.text_type(provider_location),
                      'metadata': {'device-meta-key-1': 'device-meta-value-1',
                                   'device-meta-key-2': 'device-meta-value-2',
                                   'user-meta-key-1': 'user-meta-value-1',
                                   'user-meta-key-2': 'user-meta-value-2'}}
        volume = deepcopy(self.data.test_volume)
        volume.metadata = {'user-meta-key-1': 'user-meta-value-1',
                           'user-meta-key-2': 'user-meta-value-2'}
        with mock.patch.object(
                self.common, '_check_lun_valid_for_cinder_management',
                return_value=('vol1', 'test_sg')):
            model_update = self.common.manage_existing(volume, external_ref)
            self.assertEqual(ref_update, model_update)

    @mock.patch.object(rest.PowerMaxRest, 'get_volume_list',
                       return_value=[tpd.PowerMaxData.device_id3])
    @mock.patch.object(
        rest.PowerMaxRest, 'get_masking_views_from_storage_group',
        return_value=None)
    @mock.patch.object(rest.PowerMaxRest, 'is_vol_in_rep_session',
                       return_value=(False, False, None))
    def test_check_lun_valid_for_cinder_management(
            self, mock_rep, mock_mv, mock_list):
        external_ref = {u'source-name': u'00003'}
        vol, source_sg = self.common._check_lun_valid_for_cinder_management(
            self.data.array, self.data.device_id3,
            self.data.test_volume.id, external_ref)
        self.assertEqual(vol, '123')
        self.assertIsNone(source_sg)

    @mock.patch.object(rest.PowerMaxRest, 'get_volume_list',
                       return_value=[tpd.PowerMaxData.device_id4])
    @mock.patch.object(
        rest.PowerMaxRest, 'get_masking_views_from_storage_group',
        return_value=None)
    @mock.patch.object(rest.PowerMaxRest, 'is_vol_in_rep_session',
                       return_value=(False, False, None))
    def test_check_lun_valid_for_cinder_management_multiple_sg_exception(
            self, mock_rep, mock_mv, mock_list):
        external_ref = {u'source-name': u'00004'}
        self.assertRaises(
            exception.ManageExistingInvalidReference,
            self.common._check_lun_valid_for_cinder_management,
            self.data.array, self.data.device_id4,
            self.data.test_volume.id, external_ref)

    @mock.patch.object(rest.PowerMaxRest, 'get_volume_list',
                       return_value=[tpd.PowerMaxData.device_id3])
    @mock.patch.object(rest.PowerMaxRest, 'get_volume',
                       side_effect=[None,
                                    tpd.PowerMaxData.volume_details[2],
                                    tpd.PowerMaxData.volume_details[2],
                                    tpd.PowerMaxData.volume_details[1]])
    @mock.patch.object(
        rest.PowerMaxRest, 'get_masking_views_from_storage_group',
        side_effect=[tpd.PowerMaxData.sg_details[1]['maskingview'],
                     None])
    @mock.patch.object(
        rest.PowerMaxRest, 'get_storage_groups_from_volume',
        return_value=([tpd.PowerMaxData.defaultstoragegroup_name]))
    @mock.patch.object(rest.PowerMaxRest, 'is_vol_in_rep_session',
                       side_effect=[(True, False, []), (False, False, None)])
    def test_check_lun_valid_for_cinder_management_exception(
            self, mock_rep, mock_sg, mock_mvs, mock_get_vol, mock_list):
        external_ref = {u'source-name': u'00003'}
        for x in range(0, 3):
            self.assertRaises(
                exception.ManageExistingInvalidReference,
                self.common._check_lun_valid_for_cinder_management,
                self.data.array, self.data.device_id3,
                self.data.test_volume.id, external_ref)
        self.assertRaises(exception.ManageExistingAlreadyManaged,
                          self.common._check_lun_valid_for_cinder_management,
                          self.data.array, self.data.device_id3,
                          self.data.test_volume.id, external_ref)

    @mock.patch.object(rest.PowerMaxRest, 'get_volume_list',
                       return_value=[tpd.PowerMaxData.device_id])
    @mock.patch.object(
        rest.PowerMaxRest, 'get_masking_views_from_storage_group',
        return_value=None)
    @mock.patch.object(rest.PowerMaxRest, 'is_vol_in_rep_session',
                       return_value=(False, False, None))
    def test_check_lun_valid_for_cinder_management_non_FBA(
            self, mock_rep, mock_mv, mock_list):
        external_ref = {u'source-name': u'00004'}
        self.assertRaises(
            exception.ManageExistingVolumeTypeMismatch,
            self.common._check_lun_valid_for_cinder_management,
            self.data.array, self.data.device_id4,
            self.data.test_volume.id, external_ref)

    def test_manage_existing_get_size(self):
        external_ref = {u'source-name': u'00001'}
        size = self.common.manage_existing_get_size(
            self.data.test_volume, external_ref)
        self.assertEqual(2, size)

    def test_manage_existing_get_size_exception(self):
        external_ref = {u'source-name': u'00001'}
        with mock.patch.object(self.rest, 'get_size_of_device_on_array',
                               return_value=3.5):
            self.assertRaises(exception.ManageExistingInvalidReference,
                              self.common.manage_existing_get_size,
                              self.data.test_volume, external_ref)

    @mock.patch.object(rest.PowerMaxRest, 'is_vol_in_rep_session',
                       return_value=(False, False, False))
    @mock.patch.object(common.PowerMaxCommon,
                       '_remove_vol_and_cleanup_replication')
    @mock.patch.object(common.PowerMaxCommon, '_cleanup_device_snapvx')
    def test_unmanage_success(self, mck_cleanup_snaps, mock_rm, mck_sess):
        volume = self.data.test_volume
        with mock.patch.object(self.rest, 'rename_volume') as mock_rename:
            self.common.unmanage(volume)
            mock_rename.assert_called_once_with(
                self.data.array, self.data.device_id,
                self.data.test_volume.id)
        # Test for success when create storage group fails
        with mock.patch.object(self.rest, 'rename_volume') as mock_rename:
            with mock.patch.object(
                    self.provision, 'create_storage_group',
                    side_effect=exception.VolumeBackendAPIException):
                self.common.unmanage(volume)
                mock_rename.assert_called_once_with(
                    self.data.array, self.data.device_id,
                    self.data.test_volume.id)

    def test_unmanage_device_not_found(self):
        volume = self.data.test_volume
        with mock.patch.object(self.common, '_find_device_on_array',
                               return_value=None):
            with mock.patch.object(self.rest, 'rename_volume') as mock_rename:
                self.common.unmanage(volume)
                mock_rename.assert_not_called()

    @mock.patch.object(rest.PowerMaxRest, 'is_vol_in_rep_session',
                       return_value=(True, True, False))
    @mock.patch.object(common.PowerMaxCommon, '_cleanup_device_snapvx')
    def test_unmanage_temp_snapshot_links(self, mck_cleanup_snaps, mck_sess):
        volume = self.data.test_volume
        self.assertRaises(exception.VolumeIsBusy, self.common.unmanage,
                          volume)

    @mock.patch.object(common.PowerMaxCommon, '_slo_workload_migration')
    def test_retype(self, mock_migrate):
        device_id = self.data.device_id
        volume_name = self.data.test_volume.name
        extra_specs = deepcopy(self.data.extra_specs_intervals_set)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        volume = self.data.test_volume
        new_type = {'extra_specs': {}}
        host = {'host': self.data.new_host}
        self.common.retype(volume, new_type, host)
        mock_migrate.assert_called_once_with(
            device_id, volume, host, volume_name, new_type, extra_specs)
        with mock.patch.object(
                self.common, '_find_device_on_array', return_value=None):
            self.assertFalse(self.common.retype(volume, new_type, host))

    def test_retype_attached_vol(self):
        host = {'host': self.data.new_host}
        new_type = {'extra_specs': {}}
        with mock.patch.object(
                self.common, '_find_device_on_array', return_value=True):
            with mock.patch.object(self.common,
                                   '_slo_workload_migration') as mock_retype:
                self.common.retype(self.data.test_attached_volume,
                                   new_type, host)
                mock_retype.assert_called_once()

    @mock.patch.object(utils.PowerMaxUtils, 'is_retype_supported',
                       return_value=False)
    def test_retype_not_supported(self, mck_retype):
        volume = self.data.test_volume
        new_type = {'extra_specs': self.data.rep_extra_specs}
        host = self.data.new_host
        self.assertFalse(self.common.retype(volume, new_type, host))

    @mock.patch.object(
        common.PowerMaxCommon, '_initial_setup',
        return_value=tpd.PowerMaxData.rep_extra_specs_rep_config)
    @mock.patch.object(provision.PowerMaxProvision, 'verify_slo_workload',
                       return_value=(True, True))
    @mock.patch.object(common.PowerMaxCommon, '_slo_workload_migration')
    def test_retype_promotion_extra_spec_update(
            self, mck_migrate, mck_slo, mck_setup):
        device_id = self.data.device_id
        volume_name = self.data.test_rep_volume.name
        extra_specs = deepcopy(self.data.rep_extra_specs_rep_config)
        rep_config = extra_specs[utils.REP_CONFIG]
        rep_extra_specs = self.common._get_replication_extra_specs(
            extra_specs, rep_config)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        volume = self.data.test_rep_volume
        new_type = {'extra_specs': {}}
        host = {'host': self.data.new_host}
        self.common.promotion = True
        self.common.retype(volume, new_type, host)
        self.common.promotion = False
        mck_migrate.assert_called_once_with(
            device_id, volume, host, volume_name, new_type, rep_extra_specs)

    def test_slo_workload_migration_valid(self):
        device_id = self.data.device_id
        volume_name = self.data.test_volume.name
        extra_specs = self.data.extra_specs
        new_type = {'extra_specs': self.data.vol_type_extra_specs}
        volume = self.data.test_volume
        host = {'host': self.data.new_host}
        with mock.patch.object(self.common, '_migrate_volume') as mock_migrate:
            self.common._slo_workload_migration(
                device_id, volume, host, volume_name, new_type, extra_specs)
            mock_migrate.assert_called_once_with(
                extra_specs[utils.ARRAY], volume, device_id,
                extra_specs[utils.SRP], 'Silver',
                'OLTP', volume_name, new_type, extra_specs)

    def test_slo_workload_migration_not_valid(self):
        device_id = self.data.device_id
        volume_name = self.data.test_volume.name
        extra_specs = self.data.extra_specs
        volume = self.data.test_volume
        new_type = {'extra_specs': self.data.vol_type_extra_specs}
        host = {'host': self.data.new_host}
        with mock.patch.object(
                self.common, '_is_valid_for_storage_assisted_migration',
                return_value=(False, 'Silver', 'OLTP')):
            migrate_status = self.common._slo_workload_migration(
                device_id, volume, host, volume_name, new_type, extra_specs)
            self.assertFalse(migrate_status)

    def test_slo_workload_migration_same_hosts(self):
        device_id = self.data.device_id
        volume_name = self.data.test_volume.name
        extra_specs = self.data.extra_specs
        volume = self.data.test_volume
        host = {'host': self.data.fake_host}
        new_type = {'extra_specs': {'slo': 'Bronze'}}
        migrate_status = self.common._slo_workload_migration(
            device_id, volume, host, volume_name, new_type, extra_specs)
        self.assertFalse(migrate_status)

    @mock.patch.object(rest.PowerMaxRest, 'is_compression_capable',
                       return_value=True)
    def test_slo_workload_migration_same_host_change_compression(
            self, mock_cap):
        device_id = self.data.device_id
        volume_name = self.data.test_volume.name
        extra_specs = self.data.extra_specs
        volume = self.data.test_volume
        host = {'host': self.data.fake_host}
        new_type = {'extra_specs': {utils.DISABLECOMPRESSION: "true"}}

        with mock.patch.object(
                self.common, '_is_valid_for_storage_assisted_migration',
                return_value=(True, self.data.slo, self.data.workload)):
            with mock.patch.object(
                    self.common, '_migrate_volume') as mock_migrate:
                migrate_status = self.common._slo_workload_migration(
                    device_id, volume, host, volume_name, new_type,
                    extra_specs)
                self.assertTrue(bool(migrate_status))
                mock_migrate.assert_called_once_with(
                    extra_specs[utils.ARRAY], volume, device_id,
                    extra_specs[utils.SRP], self.data.slo,
                    self.data.workload, volume_name, new_type, extra_specs)

    @mock.patch.object(
        common.PowerMaxCommon, 'get_volume_metadata', return_value='')
    @mock.patch.object(
        common.PowerMaxCommon, '_retype_volume',
        return_value=(True, tpd.PowerMaxData.defaultstoragegroup_name))
    def test_migrate_volume_success_no_rep(self, mck_retype, mck_get):
        array_id = self.data.array
        volume = self.data.test_volume
        device_id = self.data.device_id
        srp = self.data.srp
        target_slo = self.data.slo_silver
        target_workload = self.data.workload
        volume_name = volume.name
        new_type = {'extra_specs': {}}
        extra_specs = self.data.extra_specs

        target_extra_specs = {
            utils.SRP: srp, utils.ARRAY: array_id, utils.SLO: target_slo,
            utils.WORKLOAD: target_workload,
            utils.INTERVAL: extra_specs[utils.INTERVAL],
            utils.RETRIES: extra_specs[utils.RETRIES],
            utils.DISABLECOMPRESSION: False}

        success, model_update = self.common._migrate_volume(
            array_id, volume, device_id, srp, target_slo, target_workload,
            volume_name, new_type, extra_specs)
        mck_retype.assert_called_once_with(
            array_id, srp, device_id, volume, volume_name, extra_specs,
            target_slo, target_workload, target_extra_specs)
        self.assertTrue(success)

    @mock.patch.object(utils.PowerMaxUtils, 'get_rep_config',
                       return_value=tpd.PowerMaxData.rep_config_metro)
    @mock.patch.object(utils.PowerMaxUtils, 'is_replication_enabled',
                       side_effect=[False, True])
    @mock.patch.object(common.PowerMaxCommon, '_validate_rdfg_status')
    @mock.patch.object(rest.PowerMaxRest, 'get_slo_list', return_value=[])
    @mock.patch.object(rest.PowerMaxRest, 'get_volume_snapshot_list',
                       return_value=[{'snapshotName': 'name',
                                      'linkedDevices': 'details'}])
    def test_migrate_to_metro_exception_on_linked_snapshot_source(
            self, mck_get, mck_slo, mck_validate, mck_rep, mck_config):
        array_id = self.data.array
        volume = self.data.test_volume
        device_id = self.data.device_id
        srp = self.data.srp
        target_slo = self.data.slo_silver
        target_workload = self.data.workload
        volume_name = volume.name
        target_extra_specs = self.data.rep_extra_specs_rep_config_metro
        new_type = {'extra_specs': target_extra_specs}
        extra_specs = self.data.extra_specs
        self.assertRaises(
            exception.VolumeBackendAPIException, self.common._migrate_volume,
            array_id, volume, device_id, srp, target_slo, target_workload,
            volume_name, new_type, extra_specs)

    @mock.patch.object(common.PowerMaxCommon, '_cleanup_device_snapvx')
    @mock.patch.object(utils.PowerMaxUtils, 'get_rep_config',
                       return_value=tpd.PowerMaxData.rep_config_metro)
    @mock.patch.object(utils.PowerMaxUtils, 'is_replication_enabled',
                       side_effect=[False, True])
    @mock.patch.object(common.PowerMaxCommon, '_validate_rdfg_status')
    @mock.patch.object(rest.PowerMaxRest, 'get_slo_list', return_value=[])
    @mock.patch.object(rest.PowerMaxRest, 'get_volume_snapshot_list',
                       return_value=[{'snapshotName': 'name'}])
    @mock.patch.object(rest.PowerMaxRest, 'find_snap_vx_sessions',
                       return_value=('', {'source_vol_id': 'source_vol_id',
                                          'snap_name': 'snap_name'}))
    def test_migrate_to_metro_exception_on_snapshot_target(
            self, mck_find, mck_snap, mck_slo, mck_validate, mck_rep,
            mck_config, mck_cleanup):
        array_id = self.data.array
        volume = self.data.test_volume
        device_id = self.data.device_id
        srp = self.data.srp
        target_slo = self.data.slo_silver
        target_workload = self.data.workload
        volume_name = volume.name
        target_extra_specs = self.data.rep_extra_specs_rep_config_metro
        new_type = {'extra_specs': target_extra_specs}
        extra_specs = self.data.extra_specs
        self.assertRaises(
            exception.VolumeBackendAPIException, self.common._migrate_volume,
            array_id, volume, device_id, srp, target_slo, target_workload,
            volume_name, new_type, extra_specs)

    @mock.patch.object(rest.PowerMaxRest, 'get_storage_group_rdf_group_state',
                       return_value=['activebias'])
    @mock.patch.object(common.PowerMaxCommon,
                       '_post_retype_srdf_protect_storage_group',
                       return_value=(True, True, True))
    @mock.patch.object(utils.PowerMaxUtils, 'get_volume_element_name',
                       return_value=tpd.PowerMaxData.volume_id)
    @mock.patch.object(
        common.PowerMaxCommon, 'configure_volume_replication',
        return_value=('first_vol_in_rdf_group', True, True,
                      tpd.PowerMaxData.rep_extra_specs_mgmt, False))
    @mock.patch.object(common.PowerMaxCommon, '_retype_volume')
    @mock.patch.object(rest.PowerMaxRest, 'srdf_resume_replication')
    @mock.patch.object(
        common.PowerMaxCommon, 'break_rdf_device_pair_session',
        return_value=(tpd.PowerMaxData.rep_extra_specs_mgmt, True))
    @mock.patch.object(common.PowerMaxCommon, '_retype_remote_volume')
    @mock.patch.object(utils.PowerMaxUtils, 'is_replication_enabled',
                       return_value=True)
    def test_cleanup_on_migrate_failure(
            self, mck_rep_enabled, mck_retype_remote, mck_break, mck_resume,
            mck_retype, mck_configure, mck_get_vname, mck_protect, mck_states):
        rdf_pair_broken = True
        rdf_pair_created = True
        vol_retyped = True
        remote_retyped = True
        extra_specs = deepcopy(self.data.extra_specs_rep_enabled)
        target_extra_specs = deepcopy(self.data.extra_specs_rep_enabled)
        rep_extra_specs = deepcopy(self.data.rep_extra_specs_mgmt)
        volume = self.data.test_volume
        volume_name = self.data.volume_id
        device_id = self.data.device_id
        source_sg = self.data.storagegroup_name_f
        array = self.data.array
        srp = extra_specs[utils.SRP]
        slo = extra_specs[utils.SLO]
        workload = extra_specs[utils.WORKLOAD]
        rep_mode = utils.REP_ASYNC
        extra_specs[utils.REP_MODE] = rep_mode
        self.common._cleanup_on_migrate_failure(
            rdf_pair_broken, rdf_pair_created, vol_retyped,
            remote_retyped, extra_specs, target_extra_specs, volume,
            volume_name, device_id, source_sg)
        mck_rep_enabled.assert_called_once_with(extra_specs)
        mck_retype_remote.assert_called_once_with(
            array, volume, device_id, volume_name,
            rep_mode, True, extra_specs)
        mck_break.assert_called_once_with(
            array, device_id, volume_name, extra_specs, volume)
        mck_resume.assert_called_once_with(
            array, rep_extra_specs['mgmt_sg_name'],
            rep_extra_specs['rdf_group_no'], rep_extra_specs)
        mck_retype.assert_called_once_with(
            array, srp, device_id, volume, volume_name,
            target_extra_specs, slo, workload, extra_specs)
        mck_configure.assert_called_once_with(
            array, volume, device_id, extra_specs)
        mck_get_vname.assert_called_once_with(volume.id)
        mck_protect.assert_called_once_with(
            array, source_sg, device_id, volume_name,
            rep_extra_specs, volume)

    @mock.patch.object(
        masking.PowerMaxMasking, 'return_volume_to_volume_group')
    @mock.patch.object(
        masking.PowerMaxMasking, 'move_volume_between_storage_groups')
    @mock.patch.object(masking.PowerMaxMasking, 'add_child_sg_to_parent_sg')
    @mock.patch.object(rest.PowerMaxRest, 'create_storage_group')
    @mock.patch.object(rest.PowerMaxRest, 'get_storage_group_list',
                       return_value=['sg'])
    def test_cleanup_on_retype_volume_failure_moved_sg(
            self, mck_get_sgs, mck_create_sg, mck_add_child, mck_move,
            mck_return):
        created_child_sg = False
        add_sg_to_parent = False
        got_default_sg = False
        moved_between_sgs = True
        extra_specs = deepcopy(self.data.extra_specs_rep_enabled)
        array = extra_specs[utils.ARRAY]
        source_sg = self.data.storagegroup_name_f
        parent_sg = self.data.parent_sg_f
        target_sg_name = self.data.storagegroup_name_i
        device_id = self.data.device_id
        volume = self.data.test_volume
        volume_name = self.data.volume_id
        self.common._cleanup_on_retype_volume_failure(
            created_child_sg, add_sg_to_parent, got_default_sg,
            moved_between_sgs, array, source_sg, parent_sg, target_sg_name,
            extra_specs, device_id, volume, volume_name)
        mck_get_sgs.assert_called_once_with(array)
        mck_create_sg.assert_called_once_with(
            array, source_sg, extra_specs['srp'], extra_specs['slo'],
            extra_specs['workload'], extra_specs, False)
        mck_add_child.assert_called_once_with(
            array, source_sg, parent_sg, extra_specs)
        mck_move.assert_called_once_with(
            array, device_id, target_sg_name, source_sg, extra_specs,
            force=True, parent_sg=parent_sg)
        mck_return.assert_called_once_with(
            array, volume, device_id, volume_name, extra_specs)

    @mock.patch.object(rest.PowerMaxRest, 'delete_storage_group')
    @mock.patch.object(rest.PowerMaxRest, 'get_volumes_in_storage_group',
                       return_value=[])
    def test_cleanup_on_retype_volume_failure_got_default(
            self, mck_get_vols, mck_del_sg):
        created_child_sg = False
        add_sg_to_parent = False
        got_default_sg = True
        moved_between_sgs = False
        extra_specs = deepcopy(self.data.extra_specs_rep_enabled)
        array = extra_specs[utils.ARRAY]
        source_sg = self.data.storagegroup_name_f
        parent_sg = self.data.parent_sg_f
        target_sg_name = self.data.storagegroup_name_i
        device_id = self.data.device_id
        volume = self.data.test_volume
        volume_name = self.data.volume_id
        self.common._cleanup_on_retype_volume_failure(
            created_child_sg, add_sg_to_parent, got_default_sg,
            moved_between_sgs, array, source_sg, parent_sg, target_sg_name,
            extra_specs, device_id, volume, volume_name)
        mck_get_vols.assert_called_once_with(array, target_sg_name)
        mck_del_sg.assert_called_once_with(array, target_sg_name)

    @mock.patch.object(rest.PowerMaxRest, 'delete_storage_group')
    @mock.patch.object(rest.PowerMaxRest, 'remove_child_sg_from_parent_sg')
    def test_cleanup_on_retype_volume_failure_created_child(
            self, mck_remove_child_sg, mck_del_sg):
        created_child_sg = True
        add_sg_to_parent = True
        got_default_sg = False
        moved_between_sgs = False
        extra_specs = deepcopy(self.data.extra_specs_rep_enabled)
        array = extra_specs[utils.ARRAY]
        source_sg = self.data.storagegroup_name_f
        parent_sg = self.data.parent_sg_f
        target_sg_name = self.data.storagegroup_name_i
        device_id = self.data.device_id
        volume = self.data.test_volume
        volume_name = self.data.volume_id
        self.common._cleanup_on_retype_volume_failure(
            created_child_sg, add_sg_to_parent, got_default_sg,
            moved_between_sgs, array, source_sg, parent_sg, target_sg_name,
            extra_specs, device_id, volume, volume_name)
        mck_remove_child_sg.assert_called_once_with(
            array, target_sg_name, parent_sg, extra_specs)
        mck_del_sg.assert_called_once_with(array, target_sg_name)

    def test_is_valid_for_storage_assisted_migration_true(self):
        device_id = self.data.device_id
        host = {'host': self.data.new_host}
        volume_name = self.data.test_volume.name
        ref_return = (True, 'Silver', 'OLTP')
        return_val = self.common._is_valid_for_storage_assisted_migration(
            device_id, host, self.data.array,
            self.data.srp, volume_name, False, False, self.data.slo,
            self.data.workload, False)
        self.assertEqual(ref_return, return_val)
        # No current sgs found
        with mock.patch.object(self.rest, 'get_storage_groups_from_volume',
                               return_value=None):
            return_val = self.common._is_valid_for_storage_assisted_migration(
                device_id, host, self.data.array, self.data.srp,
                volume_name, False, False, self.data.slo, self.data.workload,
                False)
            self.assertEqual(ref_return, return_val)
        host = {'host': 'HostX@Backend#Silver+SRP_1+000197800123'}
        ref_return = (True, 'Silver', 'NONE')
        return_val = self.common._is_valid_for_storage_assisted_migration(
            device_id, host, self.data.array,
            self.data.srp, volume_name, False, False, self.data.slo,
            self.data.workload, False)
        self.assertEqual(ref_return, return_val)

    def test_is_valid_for_storage_assisted_migration_false(self):
        device_id = self.data.device_id
        volume_name = self.data.test_volume.name
        ref_return = (False, None, None)
        # IndexError
        host = {'host': 'HostX@Backend#Silver+SRP_1+000197800123+dummy+data'}
        return_val = self.common._is_valid_for_storage_assisted_migration(
            device_id, host, self.data.array,
            self.data.srp, volume_name, False, False, self.data.slo,
            self.data.workload, False)
        self.assertEqual(ref_return, return_val)
        # Wrong array
        host2 = {'host': 'HostX@Backend#Silver+OLTP+SRP_1+00012345678'}
        return_val = self.common._is_valid_for_storage_assisted_migration(
            device_id, host2, self.data.array,
            self.data.srp, volume_name, False, False, self.data.slo,
            self.data.workload, False)
        self.assertEqual(ref_return, return_val)
        # Wrong srp
        host3 = {'host': 'HostX@Backend#Silver+OLTP+SRP_2+000197800123'}
        return_val = self.common._is_valid_for_storage_assisted_migration(
            device_id, host3, self.data.array,
            self.data.srp, volume_name, False, False, self.data.slo,
            self.data.workload, False)
        self.assertEqual(ref_return, return_val)
        # Already in correct sg
        with mock.patch.object(
                self.common.provision,
                'get_slo_workload_settings_from_storage_group',
                return_value='Diamond+DSS') as mock_settings:
            host4 = {'host': self.data.fake_host}
            return_val = self.common._is_valid_for_storage_assisted_migration(
                device_id, host4, self.data.array,
                self.data.srp, volume_name, False, False, self.data.slo,
                self.data.workload, False)
            self.assertEqual(ref_return, return_val)
            mock_settings.assert_called_once()

    def test_is_valid_for_storage_assisted_migration_next_gen(self):
        device_id = self.data.device_id
        host = {'host': self.data.new_host}
        volume_name = self.data.test_volume.name
        ref_return = (True, 'Silver', 'NONE')
        with mock.patch.object(self.rest, 'is_next_gen_array',
                               return_value=True):
            return_val = self.common._is_valid_for_storage_assisted_migration(
                device_id, host, self.data.array,
                self.data.srp, volume_name, False, False, self.data.slo,
                self.data.workload, False)
            self.assertEqual(ref_return, return_val)

    def test_is_valid_for_storage_assisted_migration_promotion_change_comp(
            self):
        device_id = self.data.device_id
        host = {'host': self.data.new_host}
        volume_name = self.data.test_volume.name
        ref_return = (False, None, None)
        self.common.promotion = True
        return_val = self.common._is_valid_for_storage_assisted_migration(
            device_id, host, self.data.array,
            self.data.srp, volume_name, True, False, self.data.slo_silver,
            self.data.workload, False)
        self.common.promotion = False
        self.assertEqual(ref_return, return_val)

    def test_is_valid_for_storage_assisted_migration_promotion_change_slo(
            self):
        device_id = self.data.device_id
        host = {'host': self.data.new_host}
        volume_name = self.data.test_volume.name
        ref_return = (False, None, None)
        self.common.promotion = True
        return_val = self.common._is_valid_for_storage_assisted_migration(
            device_id, host, self.data.array,
            self.data.srp, volume_name, False, False, self.data.slo,
            self.data.workload, False)
        self.common.promotion = False
        self.assertEqual(ref_return, return_val)

    def test_is_valid_for_storage_assisted_migration_promotion_change_workload(
            self):
        device_id = self.data.device_id
        host = {'host': self.data.new_host}
        volume_name = self.data.test_volume.name
        ref_return = (False, None, None)
        self.common.promotion = True
        return_val = self.common._is_valid_for_storage_assisted_migration(
            device_id, host, self.data.array,
            self.data.srp, volume_name, False, False, self.data.slo_silver,
            'fail_workload', False)
        self.common.promotion = False
        self.assertEqual(ref_return, return_val)

    def test_is_valid_for_storage_assisted_migration_promotion_target_not_rep(
            self):
        device_id = self.data.device_id
        host = {'host': self.data.new_host}
        volume_name = self.data.test_volume.name
        ref_return = (False, None, None)
        self.common.promotion = True
        return_val = self.common._is_valid_for_storage_assisted_migration(
            device_id, host, self.data.array,
            self.data.srp, volume_name, False, False, self.data.slo_silver,
            'OLTP', True)
        self.common.promotion = False
        self.assertEqual(ref_return, return_val)

    def test_find_volume_group(self):
        group = self.data.test_group_1
        array = self.data.array
        volume_group = self.common._find_volume_group(array, group)
        ref_group = self.data.sg_details_rep[0]
        self.assertEqual(ref_group, volume_group)

    def test_get_volume_device_ids(self):
        array = self.data.array
        volumes = [self.data.test_volume]
        ref_device_ids = [self.data.device_id]
        device_ids = self.common._get_volume_device_ids(volumes, array)
        self.assertEqual(ref_device_ids, device_ids)

    @mock.patch.object(common.PowerMaxCommon, '_find_device_on_array',
                       return_value=tpd.PowerMaxData.device_id)
    def test_get_volume_device_ids_remote_volumes(self, mck_find):
        array = self.data.array
        volumes = [self.data.test_rep_volume]
        ref_device_ids = [self.data.device_id]
        replication_details = ast.literal_eval(
            self.data.test_rep_volume.replication_driver_data)
        remote_array = replication_details.get(utils.ARRAY)
        specs = {utils.ARRAY: remote_array}
        device_ids = self.common._get_volume_device_ids(volumes, array, True)
        self.assertEqual(ref_device_ids, device_ids)
        mck_find.assert_called_once_with(
            self.data.test_rep_volume, specs, True)

    def test_get_members_of_volume_group(self):
        array = self.data.array
        group_name = self.data.storagegroup_name_source
        ref_volumes = [self.data.device_id, self.data.device_id2]
        member_device_ids = self.common._get_members_of_volume_group(
            array, group_name)
        self.assertEqual(ref_volumes, member_device_ids)

    def test_get_members_of_volume_group_empty(self):
        array = self.data.array
        group_name = self.data.storagegroup_name_source
        with mock.patch.object(
                self.rest, 'get_volumes_in_storage_group',
                return_value=None):
            member_device_ids = self.common._get_members_of_volume_group(
                array, group_name
            )
        self.assertIsNone(member_device_ids)

    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                       return_value=True)
    def test_create_group_replica(self, mock_check):
        source_group = self.data.test_group_1
        snap_name = self.data.group_snapshot_name
        with mock.patch.object(
                self.common,
                '_create_group_replica') as mock_create_replica:
            self.common._create_group_replica(
                source_group, snap_name)
            mock_create_replica.assert_called_once_with(
                source_group, snap_name)

    def test_create_group_replica_exception(self):
        source_group = self.data.test_group_failed
        snap_name = self.data.group_snapshot_name
        with mock.patch.object(
                volume_utils, 'is_group_a_cg_snapshot_type',
                return_value=True):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.common._create_group_replica,
                              source_group,
                              snap_name)

    def test_create_group_snapshot(self):
        context = None
        group_snapshot = self.data.test_group_snapshot_1
        snapshots = []
        ref_model_update = {'status': fields.GroupStatus.AVAILABLE}
        with mock.patch.object(
                volume_utils, 'is_group_a_cg_snapshot_type',
                return_value=True):
            model_update, snapshots_model_update = (
                self.common.create_group_snapshot(
                    context, group_snapshot, snapshots))
            self.assertEqual(ref_model_update, model_update)

    def test_create_group_snapshot_exception(self):
        context = None
        group_snapshot = self.data.test_group_snapshot_failed
        snapshots = []
        with mock.patch.object(
                volume_utils, 'is_group_a_cg_snapshot_type',
                return_value=True):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.common.create_group_snapshot,
                              context,
                              group_snapshot,
                              snapshots)

    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                       return_value=True)
    @mock.patch.object(volume_utils, 'is_group_a_type', return_value=False)
    def test_create_group(self, mock_type, mock_cg_type):
        ref_model_update = {'status': fields.GroupStatus.AVAILABLE}
        model_update = self.common.create_group(None, self.data.test_group_1)
        self.assertEqual(ref_model_update, model_update)

    @mock.patch.object(provision.PowerMaxProvision, 'create_volume_group',
                       side_effect=exception.CinderException)
    @mock.patch.object(volume_utils, 'is_group_a_type', return_value=False)
    def test_create_group_exception(self, mock_type, mock_create):
        context = None
        group = self.data.test_group_failed
        with mock.patch.object(
                volume_utils, 'is_group_a_cg_snapshot_type',
                return_value=True):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.common.create_group,
                              context, group)

    def test_delete_group_snapshot(self):
        group_snapshot = self.data.test_group_snapshot_1
        snapshots = []
        context = None
        ref_model_update = {'status': fields.GroupSnapshotStatus.DELETED}
        with mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                               return_value=True):
            model_update, snapshots_model_update = (
                self.common.delete_group_snapshot(context,
                                                  group_snapshot, snapshots))
            self.assertEqual(ref_model_update, model_update)

    def test_delete_group_snapshot_success(self):
        group_snapshot = self.data.test_group_snapshot_1
        snapshots = []
        ref_model_update = {'status': fields.GroupSnapshotStatus.DELETED}
        with mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                               return_value=True):
            model_update, snapshots_model_update = (
                self.common._delete_group_snapshot(group_snapshot,
                                                   snapshots))
            self.assertEqual(ref_model_update, model_update)

    def test_delete_group_snapshot_failed(self):
        group_snapshot = self.data.test_group_snapshot_failed
        snapshots = []
        ref_model_update = (
            {'status': fields.GroupSnapshotStatus.ERROR_DELETING})
        with mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                               return_value=True):
            model_update, snapshots_model_update = (
                self.common._delete_group_snapshot(group_snapshot,
                                                   snapshots))
            self.assertEqual(ref_model_update, model_update)

    @mock.patch.object(volume_utils, 'is_group_a_type',
                       return_value=False)
    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                       return_value=True)
    def test_update_group(self, mock_cg_type, mock_type_check):
        group = self.data.test_group_1
        add_vols = [self.data.test_volume]
        remove_vols = []
        ref_model_update = {'status': fields.GroupStatus.AVAILABLE}
        model_update, __, __ = self.common.update_group(
            group, add_vols, remove_vols)
        self.assertEqual(ref_model_update, model_update)

    @mock.patch.object(common.PowerMaxCommon, '_find_volume_group',
                       return_value=None)
    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                       return_value=True)
    def test_update_group_not_found(self, mock_check, mock_grp):
        self.assertRaises(exception.GroupNotFound, self.common.update_group,
                          self.data.test_group_1, [], [])

    @mock.patch.object(common.PowerMaxCommon, '_find_volume_group',
                       side_effect=exception.VolumeBackendAPIException)
    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                       return_value=True)
    def test_update_group_exception(self, mock_check, mock_grp):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common.update_group,
                          self.data.test_group_1, [], [])

    @mock.patch.object(volume_utils, 'is_group_a_type',
                       return_value=False)
    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                       return_value=True)
    def test_update_group_remove_volumes(self, mock_cg_type, mock_type_check):
        group = self.data.test_group_1
        add_vols = []
        remove_vols = [self.data.test_volume_group_member]
        ref_model_update = {'status': fields.GroupStatus.AVAILABLE}
        with mock.patch.object(
                rest.PowerMaxRest, 'is_volume_in_storagegroup',
                return_value=False) as mock_exists:
            model_update, __, __ = self.common.update_group(
                group, add_vols, remove_vols)
            mock_exists.assert_called_once()
        self.assertEqual(ref_model_update, model_update)

    @mock.patch.object(volume_utils, 'is_group_a_type',
                       return_value=False)
    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                       return_value=True)
    def test_update_group_failover_failure(
            self, mock_cg_type, mock_type_check):
        group = self.data.test_group_1
        add_vols = []
        remove_vols = [self.data.test_volume_group_member]
        self.common.failover = True
        self.assertRaises(
            exception.VolumeBackendAPIException, self.common.update_group,
            group, add_vols, remove_vols)
        self.common.failover = False

    @mock.patch.object(volume_utils, 'is_group_a_type',
                       return_value=False)
    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                       return_value=True)
    @mock.patch.object(common.PowerMaxCommon, '_update_group_promotion')
    def test_update_group_during_promotion(
            self, mck_update, mock_cg_type, mock_type_check):
        group = self.data.test_group_1
        add_vols = []
        remove_vols = [self.data.test_volume_group_member]
        ref_model_update = {'status': fields.GroupStatus.AVAILABLE}
        self.common.promotion = True
        model_update, __, __ = self.common.update_group(
            group, add_vols, remove_vols)
        self.common.promotion = False
        mck_update.assert_called_once_with(group, add_vols, remove_vols)
        self.assertEqual(ref_model_update, model_update)

    @mock.patch.object(rest.PowerMaxRest, 'is_volume_in_storagegroup',
                       return_value=True)
    @mock.patch.object(
        common.PowerMaxCommon, '_get_replication_extra_specs',
        return_value=tpd.PowerMaxData.rep_extra_specs_rep_config)
    @mock.patch.object(
        common.PowerMaxCommon, '_initial_setup',
        return_value=tpd.PowerMaxData.ex_specs_rep_config)
    @mock.patch.object(volume_utils, 'is_group_a_type',
                       return_value=True)
    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                       return_value=True)
    @mock.patch.object(
        masking.PowerMaxMasking, 'remove_volumes_from_storage_group')
    def test_update_group_promotion(
            self, mck_rem, mock_cg_type, mock_type_check, mck_setup, mck_rep,
            mck_in_sg):
        group = self.data.test_rep_group
        add_vols = []
        remove_vols = [self.data.test_volume_group_member]
        remote_array = self.data.remote_array
        device_id = [self.data.device_id]
        group_name = self.data.storagegroup_name_source
        interval_retries_dict = {utils.INTERVAL: 1,
                                 utils.RETRIES: 1,
                                 utils.FORCE_VOL_EDIT: True}
        self.common._update_group_promotion(group, add_vols, remove_vols)
        mck_rem.assert_called_once_with(
            remote_array, device_id, group_name, interval_retries_dict)

    @mock.patch.object(volume_utils, 'is_group_a_type',
                       return_value=False)
    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                       return_value=True)
    def test_update_group_promotion_non_replicated(
            self, mock_cg_type, mock_type_check):
        group = self.data.test_group_failed
        add_vols = []
        remove_vols = [self.data.test_volume_group_member]
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common._update_group_promotion,
                          group, add_vols, remove_vols)

    @mock.patch.object(volume_utils, 'is_group_a_type',
                       return_value=True)
    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                       return_value=True)
    def test_update_group_promotion_add_volumes(
            self, mock_cg_type, mock_type_check):
        group = self.data.test_rep_group
        add_vols = [self.data.test_volume_group_member]
        remove_vols = []
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common._update_group_promotion,
                          group, add_vols, remove_vols)

    @mock.patch.object(rest.PowerMaxRest, 'get_volume_snapshot_list',
                       return_value=list())
    @mock.patch.object(volume_utils, 'is_group_a_type', return_value=False)
    def test_delete_group(self, mock_check, mck_snaps):
        group = self.data.test_group_1
        volumes = [self.data.test_volume]
        context = None
        ref_model_update = {'status': fields.GroupStatus.DELETED}
        with mock.patch.object(
                volume_utils, 'is_group_a_cg_snapshot_type',
                return_value=True), mock.patch.object(
                    self.rest, 'get_volumes_in_storage_group',
                return_value=[]):

            model_update, __ = self.common.delete_group(
                context, group, volumes)
            self.assertEqual(ref_model_update, model_update)

    @mock.patch.object(rest.PowerMaxRest, 'get_volume_snapshot_list',
                       return_value=list())
    @mock.patch.object(volume_utils, 'is_group_a_type', return_value=False)
    def test_delete_group_success(self, mock_check, mck_get_snaps):
        group = self.data.test_group_1
        volumes = []
        ref_model_update = {'status': fields.GroupStatus.DELETED}
        with mock.patch.object(
                volume_utils, 'is_group_a_cg_snapshot_type',
                return_value=True), mock.patch.object(
                    self.rest, 'get_volumes_in_storage_group',
                return_value=[]):
            model_update, __ = self.common._delete_group(group, volumes)
            self.assertEqual(ref_model_update, model_update)

    @mock.patch.object(masking.PowerMaxMasking, 'remove_and_reset_members')
    @mock.patch.object(common.PowerMaxCommon, '_cleanup_device_snapvx')
    @mock.patch.object(common.PowerMaxCommon, '_get_members_of_volume_group',
                       return_value=[tpd.PowerMaxData.device_id])
    @mock.patch.object(rest.PowerMaxRest, 'get_volume_snapshot_list',
                       return_value=[])
    @mock.patch.object(volume_utils, 'is_group_a_type', return_value=False)
    def test_delete_group_snapshot_and_volume_cleanup(
            self, mock_check, mck_get_snaps, mock_members, mock_cleanup,
            mock_remove):
        group = self.data.test_group_1
        volumes = [fake_volume.fake_volume_obj(
            context='cxt', provider_location=None)]
        with mock.patch.object(
                volume_utils, 'is_group_a_cg_snapshot_type',
                return_value=True), mock.patch.object(
                    self.rest, 'get_volumes_in_storage_group',
                return_value=[]):
            self.common._delete_group(group, volumes)
            mock_cleanup.assert_called_once()
            mock_remove.assert_called_once()

    @mock.patch.object(rest.PowerMaxRest, 'get_volume_snapshot_list',
                       return_value=list())
    def test_delete_group_already_deleted(self, mck_get_snaps):
        group = self.data.test_group_failed
        ref_model_update = {'status': fields.GroupStatus.DELETED}
        volumes = []
        with mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                               return_value=True):
            model_update, __ = self.common._delete_group(group, volumes)
            self.assertEqual(ref_model_update, model_update)

    @mock.patch.object(rest.PowerMaxRest, 'get_volume_snapshot_list',
                       return_value=list())
    @mock.patch.object(volume_utils, 'is_group_a_type', return_value=False)
    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                       return_value=True)
    def test_delete_group_failed(
            self, mock_check, mock_type_check, mck_get_snaps):
        group = self.data.test_group_1
        volumes = []
        ref_model_update = {'status': fields.GroupStatus.ERROR_DELETING}
        with mock.patch.object(
                self.rest, 'delete_storage_group',
                side_effect=exception.VolumeBackendAPIException):
            model_update, __ = self.common._delete_group(
                group, volumes)
        self.assertEqual(ref_model_update, model_update)

    @mock.patch.object(rest.PowerMaxRest, 'get_volume_snapshot_list',
                       return_value=list())
    @mock.patch.object(volume_utils, 'is_group_a_type', return_value=False)
    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                       return_value=True)
    @mock.patch.object(rest.PowerMaxRest, 'get_volumes_in_storage_group',
                       return_value=[
                           tpd.PowerMaxData.test_volume_group_member])
    @mock.patch.object(common.PowerMaxCommon, '_get_members_of_volume_group',
                       return_value=[tpd.PowerMaxData.device_id])
    @mock.patch.object(common.PowerMaxCommon, '_find_device_on_array',
                       return_value=tpd.PowerMaxData.device_id)
    @mock.patch.object(masking.PowerMaxMasking,
                       'remove_volumes_from_storage_group')
    def test_delete_group_cleanup_snapvx(
            self, mock_rem, mock_find, mock_mems, mock_vols, mock_chk1,
            mock_chk2, mck_get_snaps):
        group = self.data.test_group_1
        volumes = [self.data.test_volume_group_member]
        with mock.patch.object(
                self.common, '_cleanup_device_snapvx') as mock_cleanup_snapvx:
            self.common._delete_group(group, volumes)
            mock_cleanup_snapvx.assert_called_once()

    @mock.patch.object(rest.PowerMaxRest, 'get_volume_snapshot_list',
                       return_value=[{'snapshotName': 'name'}])
    @mock.patch.object(common.PowerMaxCommon, '_cleanup_device_snapvx')
    def test_delete_group_with_volumes_exception_on_remaining_snapshots(
            self, mck_cleanup, mck_get):
        group = self.data.test_group_1
        volumes = [self.data.test_volume_group_member]
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common._delete_group, group, volumes)

    @mock.patch.object(rest.PowerMaxRest, 'find_snap_vx_sessions',
                       return_value=('', {'source_vol_id': 'id',
                                          'snap_name': 'name'}))
    @mock.patch.object(rest.PowerMaxRest, 'get_volume_snapshot_list',
                       return_value=None)
    @mock.patch.object(common.PowerMaxCommon, '_cleanup_device_snapvx')
    def test_delete_group_with_volumes_exception_on_target_links(
            self, mck_cleanup, mck_get, mck_find):
        group = self.data.test_group_1
        volumes = [self.data.test_volume_group_member]
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common._delete_group, group, volumes)

    @mock.patch.object(rest.PowerMaxRest, 'delete_storage_group')
    @mock.patch.object(common.PowerMaxCommon, '_failover_replication',
                       return_value=(True, None))
    @mock.patch.object(masking.PowerMaxMasking, 'add_volumes_to_storage_group')
    @mock.patch.object(common.PowerMaxCommon, '_get_volume_device_ids',
                       return_value=[tpd.PowerMaxData.device_id])
    @mock.patch.object(provision.PowerMaxProvision, 'create_volume_group')
    @mock.patch.object(common.PowerMaxCommon, '_initial_setup',
                       return_value=tpd.PowerMaxData.ex_specs_rep_config_sync)
    def test_update_volume_list_from_sync_vol_list(
            self, mck_setup, mck_grp, mck_ids, mck_add, mck_fover, mck_del):
        vol_list = [self.data.test_rep_volume]
        vol_ids = [self.data.device_id]
        remote_array = self.data.remote_array
        temp_group = 'OS-23_24_007-temp-rdf-sg'
        extra_specs = self.data.ex_specs_rep_config_sync
        self.common._update_volume_list_from_sync_vol_list(vol_list, None)
        mck_grp.assert_called_once_with(remote_array, temp_group, extra_specs)
        mck_ids.assert_called_once_with(
            vol_list, remote_array, remote_volumes=True)
        mck_add.assert_called_once_with(
            remote_array, vol_ids, temp_group, extra_specs)
        mck_fover.assert_called_once_with(
            vol_list, None, temp_group, secondary_backend_id=None, host=True)
        mck_del.assert_called_once_with(remote_array, temp_group)

    @mock.patch.object(
        common.PowerMaxCommon, '_remove_vol_and_cleanup_replication')
    @mock.patch.object(
        masking.PowerMaxMasking, 'remove_volumes_from_storage_group')
    def test_rollback_create_group_from_src(
            self, mock_rm, mock_clean):
        rollback_dict = {
            'target_group_name': self.data.target_group_name,
            'snap_name': 'snap1', 'source_group_name': 'src_grp',
            'volumes': (self.data.device_id, self.data.extra_specs,
                        self.data.test_volume),
            'device_ids': [self.data.device_id],
            'interval_retries_dict': self.data.extra_specs}
        for x in range(0, 2):
            self.common._rollback_create_group_from_src(
                self.data.array, rollback_dict)
        self.assertEqual(2, mock_rm.call_count)

    def test_get_snap_src_dev_list(self):
        src_dev_ids = self.common._get_snap_src_dev_list(
            self.data.array, [self.data.test_snapshot])
        ref_dev_ids = [self.data.device_id]
        self.assertEqual(ref_dev_ids, src_dev_ids)

    def test_get_clone_vol_info(self):
        ref_dev_id = self.data.device_id
        source_vols = [self.data.test_volume,
                       self.data.test_attached_volume]
        src_snapshots = [self.data.test_snapshot]
        src_dev_id1, extra_specs1, vol_size1, tgt_vol_name1 = (
            self.common._get_clone_vol_info(
                self.data.test_clone_volume, source_vols, []))
        src_dev_id2, extra_specs2, vol_size2, tgt_vol_name2 = (
            self.common._get_clone_vol_info(
                self.data.test_clone_volume, [], src_snapshots))
        self.assertEqual(ref_dev_id, src_dev_id1)
        self.assertEqual(ref_dev_id, src_dev_id2)

    def test_get_attributes_from_cinder_config_new_and_old(self):
        kwargs_expected = (
            {'RestServerIp': '1.1.1.1', 'RestServerPort': 8443,
             'RestUserName': 'smc', 'RestPassword': 'smc', 'SSLVerify': False,
             'SerialNumber': self.data.array, 'srpName': 'SRP_1',
             'PortGroup': [self.data.port_group_name_i]})
        old_conf = tpfo.FakeConfiguration(None, 'CommonTests', 1, 1)
        configuration = tpfo.FakeConfiguration(
            None, 'CommonTests', 1, 1, san_ip='1.1.1.1', san_login='smc',
            powermax_array=self.data.array, powermax_srp='SRP_1',
            san_password='smc', san_api_port=8443,
            powermax_port_groups=[self.data.port_group_name_i])
        self.common.configuration = configuration
        kwargs_returned = self.common.get_attributes_from_cinder_config()
        self.assertEqual(kwargs_expected, kwargs_returned)
        self.common.configuration = old_conf
        kwargs = self.common.get_attributes_from_cinder_config()
        self.assertIsNone(kwargs)

    def test_get_attributes_from_cinder_config_with_port(self):
        kwargs_expected = (
            {'RestServerIp': '1.1.1.1', 'RestServerPort': 3448,
             'RestUserName': 'smc', 'RestPassword': 'smc', 'SSLVerify': False,
             'SerialNumber': self.data.array, 'srpName': 'SRP_1',
             'PortGroup': [self.data.port_group_name_i]})
        configuration = tpfo.FakeConfiguration(
            None, 'CommonTests', 1, 1, san_ip='1.1.1.1', san_login='smc',
            powermax_array=self.data.array, powermax_srp='SRP_1',
            san_password='smc', san_api_port=3448,
            powermax_port_groups=[self.data.port_group_name_i])
        self.common.configuration = configuration
        kwargs_returned = self.common.get_attributes_from_cinder_config()
        self.assertEqual(kwargs_expected, kwargs_returned)

    def test_get_attributes_from_cinder_config_no_port(self):
        kwargs_expected = (
            {'RestServerIp': '1.1.1.1', 'RestServerPort': 8443,
             'RestUserName': 'smc', 'RestPassword': 'smc', 'SSLVerify': False,
             'SerialNumber': self.data.array, 'srpName': 'SRP_1',
             'PortGroup': [self.data.port_group_name_i]})
        configuration = tpfo.FakeConfiguration(
            None, 'CommonTests', 1, 1, san_ip='1.1.1.1', san_login='smc',
            powermax_array=self.data.array, powermax_srp='SRP_1',
            san_password='smc',
            powermax_port_groups=[self.data.port_group_name_i])
        self.common.configuration = configuration
        kwargs_returned = self.common.get_attributes_from_cinder_config()
        self.assertEqual(kwargs_expected, kwargs_returned)

    def test_get_ssl_attributes_from_cinder_config(self):
        conf = tpfo.FakeConfiguration(
            None, 'CommonTests', 1, 1, san_ip='1.1.1.1', san_login='smc',
            powermax_array=self.data.array, powermax_srp='SRP_1',
            san_password='smc',
            powermax_port_groups=[self.data.port_group_name_i],
            driver_ssl_cert_verify=True,
            driver_ssl_cert_path='/path/to/cert')

        self.common.configuration = conf
        conf_returned = self.common.get_attributes_from_cinder_config()
        self.assertEqual('/path/to/cert', conf_returned['SSLVerify'])

        conf.driver_ssl_cert_verify = True
        conf.driver_ssl_cert_path = None
        conf_returned = self.common.get_attributes_from_cinder_config()
        self.assertTrue(conf_returned['SSLVerify'])

        conf.driver_ssl_cert_verify = False
        conf.driver_ssl_cert_path = None
        conf_returned = self.common.get_attributes_from_cinder_config()
        self.assertFalse(conf_returned['SSLVerify'])

    @mock.patch.object(rest.PowerMaxRest, 'get_size_of_device_on_array',
                       return_value=2.0)
    def test_manage_snapshot_get_size_success(self, mock_get_size):
        size = self.common.manage_existing_snapshot_get_size(
            self.data.test_snapshot)
        self.assertEqual(2, size)

    @mock.patch.object(rest.PowerMaxRest, 'get_volume_snaps',
                       return_value=[{'snap_name': 'snap_name',
                                      'snap_id': tpd.PowerMaxData.snap_id}])
    @mock.patch.object(
        common.PowerMaxCommon, 'get_snapshot_metadata',
        return_value={'snap-meta-key-1': 'snap-meta-value-1',
                      'snap-meta-key-2': 'snap-meta-value-2'})
    def test_manage_snapshot_success(self, mck_meta, mock_snap):
        snapshot = deepcopy(self.data.test_snapshot_manage)
        snapshot.metadata = {'user-meta-key-1': 'user-meta-value-1',
                             'user-meta-key-2': 'user-meta-value-2'}
        existing_ref = {u'source-name': u'test_snap'}
        updates_response = self.common.manage_existing_snapshot(
            snapshot, existing_ref)

        prov_loc = {'source_id': self.data.device_id,
                    'snap_name': 'OS-%s' % existing_ref['source-name']}
        updates = {'display_name': 'my_snap',
                   'provider_location': six.text_type(prov_loc),
                   'metadata': {'snap-meta-key-1': 'snap-meta-value-1',
                                'snap-meta-key-2': 'snap-meta-value-2',
                                'user-meta-key-1': 'user-meta-value-1',
                                'user-meta-key-2': 'user-meta-value-2'}}

        self.assertEqual(updates_response, updates)

    def test_manage_snapshot_fail_already_managed(self):
        snapshot = self.data.test_snapshot_manage
        existing_ref = {u'source-name': u'OS-test_snap'}

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common.manage_existing_snapshot,
                          snapshot, existing_ref)

    @mock.patch.object(utils.PowerMaxUtils, 'is_volume_failed_over',
                       return_value=True)
    def test_manage_snapshot_fail_vol_failed_over(self, mock_failed):
        snapshot = self.data.test_snapshot_manage
        existing_ref = {u'source-name': u'test_snap'}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common.manage_existing_snapshot,
                          snapshot, existing_ref)

    @mock.patch.object(rest.PowerMaxRest, 'get_volume_snap',
                       return_value=False)
    def test_manage_snapshot_fail_vol_not_snap_src(self, mock_snap):
        snapshot = self.data.test_snapshot_manage
        existing_ref = {u'source-name': u'test_snap'}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common.manage_existing_snapshot,
                          snapshot, existing_ref)

    @mock.patch.object(utils.PowerMaxUtils, 'modify_snapshot_prefix',
                       side_effect=exception.VolumeBackendAPIException)
    def test_manage_snapshot_fail_add_prefix(self, mock_mod):
        snapshot = self.data.test_snapshot_manage
        existing_ref = {u'source-name': u'test_snap'}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common.manage_existing_snapshot,
                          snapshot, existing_ref)

    @mock.patch.object(rest.PowerMaxRest, 'modify_volume_snap')
    def test_unmanage_snapshot_success(self, mock_mod, ):
        self.common.unmanage_snapshot(self.data.test_snapshot_manage)
        mock_mod.assert_called_once()

    @mock.patch.object(common.PowerMaxCommon, '_cleanup_device_snapvx')
    @mock.patch.object(rest.PowerMaxRest, 'modify_volume_snap')
    def test_unmanage_snapshot_no_snapvx_cleanup(self, mock_mod, mock_cleanup):
        self.common.unmanage_snapshot(self.data.test_snapshot_manage)
        mock_mod.assert_called_once()
        mock_cleanup.assert_not_called()

    @mock.patch.object(utils.PowerMaxUtils, 'is_volume_failed_over',
                       return_value=True)
    def test_unmanage_snapshot_fail_failover(self, mock_failed):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common.unmanage_snapshot,
                          self.data.test_snapshot_manage)

    @mock.patch.object(rest.PowerMaxRest, 'modify_volume_snap',
                       side_effect=exception.VolumeBackendAPIException)
    def test_unmanage_snapshot_fail_rename(self, mock_snap):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common.unmanage_snapshot,
                          self.data.test_snapshot_manage)

    @mock.patch.object(
        common.PowerMaxCommon, '_parse_snap_info', return_value=(
            tpd.PowerMaxData.device_id,
            tpd.PowerMaxData.snap_location['snap_name'],
            [tpd.PowerMaxData.snap_id]))
    @mock.patch.object(provision.PowerMaxProvision, 'delete_volume_snap')
    @mock.patch.object(provision.PowerMaxProvision, 'is_restore_complete',
                       return_value=True)
    @mock.patch.object(common.PowerMaxCommon, '_cleanup_device_snapvx')
    @mock.patch.object(provision.PowerMaxProvision, 'revert_volume_snapshot')
    def test_revert_to_snapshot(self, mock_revert, mock_clone,
                                mock_complete, mock_delete, mock_parse):
        volume = self.data.test_volume
        snapshot = self.data.test_snapshot
        array = self.data.array
        device_id = self.data.device_id
        snap_name = self.data.snap_location['snap_name']
        snap_id = self.data.snap_id
        extra_specs = deepcopy(self.data.extra_specs_intervals_set)
        extra_specs['storagetype:portgroupname'] = (
            self.data.port_group_name_f)
        self.common.revert_to_snapshot(volume, snapshot)
        mock_revert.assert_called_once_with(
            array, device_id, snap_name, snap_id, extra_specs)
        mock_clone.assert_called_once_with(array, device_id, extra_specs)
        mock_complete.assert_called_once_with(array, device_id,
                                              snap_name, snap_id, extra_specs)
        mock_delete.assert_called_once_with(array, snap_name, device_id,
                                            self.data.snap_id, restored=True)

    @mock.patch.object(utils.PowerMaxUtils, 'is_replication_enabled',
                       return_value=True)
    def test_revert_to_snapshot_replicated(self, mock_rep):
        volume = self.data.test_volume
        snapshot = self.data.test_snapshot
        self.assertRaises(exception.VolumeDriverException,
                          self.common.revert_to_snapshot, volume, snapshot)

    def test_get_initiator_check_flag(self):
        self.common.configuration.initiator_check = False
        initiator_check = self.common._get_initiator_check_flag()
        self.assertFalse(initiator_check)

    def test_get_initiator_check_flag_true(self):
        self.common.configuration.initiator_check = True
        initiator_check = self.common._get_initiator_check_flag()
        self.assertTrue(initiator_check)

    def test_get_manageable_volumes_success(self):
        marker = limit = offset = sort_keys = sort_dirs = None
        with mock.patch.object(
                self.rest, 'get_private_volume_list',
                return_value=self.data.priv_vol_func_response_single):
            vols_lists = self.common.get_manageable_volumes(
                marker, limit, offset, sort_keys, sort_dirs)
            expected_response = [
                {'reference': {'source-id': '00001'}, 'safe_to_manage': True,
                 'size': 1.0, 'reason_not_safe': None, 'cinder_id': None,
                 'extra_info': {'config': 'TDEV', 'emulation': 'FBA'}}]
            self.assertEqual(vols_lists, expected_response)

    def test_get_manageable_volumes_filters_set(self):
        marker, limit, offset = '00002', 2, 1
        sort_keys, sort_dirs = 'size', 'desc'
        with mock.patch.object(
                self.rest, 'get_private_volume_list',
                return_value=self.data.priv_vol_func_response_multi):
            vols_lists = self.common.get_manageable_volumes(
                marker, limit, offset, sort_keys, sort_dirs)
            expected_response = [
                {'reference': {'source-id': '00003'}, 'safe_to_manage': True,
                 'size': 300, 'reason_not_safe': None, 'cinder_id': None,
                 'extra_info': {'config': 'TDEV', 'emulation': 'FBA'}},
                {'reference': {'source-id': '00004'}, 'safe_to_manage': True,
                 'size': 400, 'reason_not_safe': None, 'cinder_id': None,
                 'extra_info': {'config': 'TDEV', 'emulation': 'FBA'}}]
            self.assertEqual(vols_lists, expected_response)

    def test_get_manageable_volumes_fail_no_vols(self):
        marker = limit = offset = sort_keys = sort_dirs = None
        with mock.patch.object(
                self.rest, 'get_private_volume_list',
                return_value=[]):
            expected_response = []
            vol_list = self.common.get_manageable_volumes(
                marker, limit, offset, sort_keys, sort_dirs)
            self.assertEqual(vol_list, expected_response)

    def test_get_manageable_volumes_fail_no_valid_vols(self):
        marker = limit = offset = sort_keys = sort_dirs = None
        with mock.patch.object(
                self.rest, 'get_private_volume_list',
                return_value=self.data.priv_vol_func_response_multi_invalid):
            expected_response = []
            vol_list = self.common.get_manageable_volumes(
                marker, limit, offset, sort_keys, sort_dirs)
            self.assertEqual(vol_list, expected_response)

    def test_get_manageable_snapshots_success(self):
        marker = limit = offset = sort_keys = sort_dirs = None
        with mock.patch.object(
                self.rest, 'get_private_volume_list',
                return_value=self.data.priv_vol_func_response_single):
            snap_list = self.common.get_manageable_snapshots(
                marker, limit, offset, sort_keys, sort_dirs)
            expected_response = [{
                'reference': {'source-name': 'testSnap1'},
                'safe_to_manage': True, 'size': 1,
                'reason_not_safe': None, 'cinder_id': None,
                'extra_info': {
                    'generation': 0, 'secured': False, 'timeToLive': 'N/A',
                    'timestamp': mock.ANY, 'snap_id': self.data.snap_id},
                'source_reference': {'source-id': '00001'}}]
            self.assertEqual(expected_response, snap_list)

    def test_get_manageable_snapshots_filters_set(self):
        marker, limit, offset = 'testSnap2', 2, 1
        sort_keys, sort_dirs = 'size', 'desc'
        with mock.patch.object(
                self.rest, 'get_private_volume_list',
                return_value=self.data.priv_vol_func_response_multi):
            vols_lists = self.common.get_manageable_snapshots(
                marker, limit, offset, sort_keys, sort_dirs)
            expected_response = [
                {'reference': {'source-name': 'testSnap3'},
                 'safe_to_manage': True, 'size': 300, 'reason_not_safe': None,
                 'cinder_id': None, 'extra_info': {
                    'snap_id': self.data.snap_id, 'secured': False,
                    'timeToLive': 'N/A', 'timestamp': mock.ANY,
                    'generation': 0},
                 'source_reference': {'source-id': '00003'}},
                {'reference': {'source-name': 'testSnap4'},
                 'safe_to_manage': True, 'size': 400, 'reason_not_safe': None,
                 'cinder_id': None, 'extra_info': {
                    'snap_id': self.data.snap_id, 'secured': False,
                    'timeToLive': 'N/A', 'timestamp': mock.ANY,
                    'generation': 0},
                 'source_reference': {'source-id': '00004'}}]
            self.assertEqual(vols_lists, expected_response)

    def test_get_manageable_snapshots_fail_no_snaps(self):
        marker = limit = offset = sort_keys = sort_dirs = None
        with mock.patch.object(self.rest, 'get_private_volume_list',
                               return_value=[]):
            expected_response = []
            vols_lists = self.common.get_manageable_snapshots(
                marker, limit, offset, sort_keys, sort_dirs)
            self.assertEqual(vols_lists, expected_response)

    def test_get_manageable_snapshots_fail_no_valid_snaps(self):
        marker = limit = offset = sort_keys = sort_dirs = None
        with mock.patch.object(
                self.rest, 'get_private_volume_list',
                return_value=self.data.priv_vol_func_response_multi_invalid):
            expected_response = []
            vols_lists = self.common.get_manageable_snapshots(
                marker, limit, offset, sort_keys, sort_dirs)
            self.assertEqual(vols_lists, expected_response)

    def test_get_slo_workload_combo_from_cinder_conf(self):
        self.common.configuration.powermax_service_level = 'Diamond'
        self.common.configuration.vmax_workload = 'DSS'
        response1 = self.common.get_attributes_from_cinder_config()
        self.assertEqual('Diamond', response1['ServiceLevel'])
        self.assertEqual('DSS', response1['Workload'])

        self.common.configuration.powermax_service_level = 'Diamond'
        self.common.configuration.vmax_workload = None
        response2 = self.common.get_attributes_from_cinder_config()
        self.assertEqual(self.common.configuration.powermax_service_level,
                         response2['ServiceLevel'])
        self.assertIsNone(response2['Workload'])

        expected_response = {
            'RestServerIp': '1.1.1.1', 'RestServerPort': 8443,
            'RestUserName': 'smc', 'RestPassword': 'smc', 'SSLVerify': False,
            'SerialNumber': '000197800123', 'srpName': 'SRP_1',
            'PortGroup': ['OS-fibre-PG']}

        self.common.configuration.powermax_service_level = None
        self.common.configuration.vmax_workload = 'DSS'
        response3 = self.common.get_attributes_from_cinder_config()
        self.assertEqual(expected_response, response3)

        self.common.configuration.powermax_service_level = None
        self.common.configuration.vmax_workload = None
        response4 = self.common.get_attributes_from_cinder_config()
        self.assertEqual(expected_response, response4)

    def test_get_u4p_failover_info(self):
        configuration = tpfo.FakeConfiguration(
            None, 'CommonTests', 1, 1, san_ip='1.1.1.1', san_login='test',
            san_password='test', san_api_port=8443,
            driver_ssl_cert_verify='/path/to/cert',
            u4p_failover_target=(self.data.u4p_failover_config[
                'u4p_failover_targets']), u4p_failover_backoff_factor='2',
            u4p_failover_retries='3', u4p_failover_timeout='10',
            u4p_primary='10.10.10.10', powermax_array=self.data.array,
            powermax_srp=self.data.srp)
        self.common.configuration = configuration
        self.common._get_u4p_failover_info()
        self.assertTrue(self.rest.u4p_failover_enabled)
        self.assertIsNotNone(self.rest.u4p_failover_targets)

    @mock.patch.object(rest.PowerMaxRest, 'set_u4p_failover_config')
    def test_get_u4p_failover_info_failover_config(self, mck_set_fo):
        configuration = tpfo.FakeConfiguration(
            None, 'CommonTests', 1, 1, san_ip='1.1.1.1', san_login='test',
            san_password='test', san_api_port=8443,
            driver_ssl_cert_verify='/path/to/cert',
            u4p_failover_target=(self.data.u4p_failover_config[
                'u4p_failover_targets']), u4p_failover_backoff_factor='2',
            u4p_failover_retries='3', u4p_failover_timeout='10',
            u4p_primary='10.10.10.10', powermax_array=self.data.array,
            powermax_srp=self.data.srp)
        expected_u4p_failover_config = {
            'u4p_failover_targets': [
                {'RestServerIp': '10.10.10.11', 'RestServerPort': '8443',
                 'RestUserName': 'test', 'RestPassword': 'test',
                 'SSLVerify': 'True', 'SerialNumber': '000197800123'},
                {'RestServerIp': '10.10.10.12', 'RestServerPort': '8443',
                 'RestUserName': 'test', 'RestPassword': 'test',
                 'SSLVerify': True, 'SerialNumber': '000197800123'},
                {'RestServerIp': '10.10.10.11', 'RestServerPort': '8443',
                 'RestUserName': 'test', 'RestPassword': 'test',
                 'SSLVerify': 'False', 'SerialNumber': '000197800123'}],
            'u4p_failover_backoff_factor': '2', 'u4p_failover_retries': '3',
            'u4p_failover_timeout': '10', 'u4p_failover_autofailback': None,
            'u4p_primary': {
                'RestServerIp': '1.1.1.1', 'RestServerPort': 8443,
                'RestUserName': 'test', 'RestPassword': 'test',
                'SerialNumber': '000197800123', 'srpName': 'SRP_1',
                'PortGroup': None, 'SSLVerify': True}}
        self.common.configuration = configuration
        self.common._get_u4p_failover_info()
        self.assertIsNotNone(self.rest.u4p_failover_targets)
        mck_set_fo.assert_called_once_with(expected_u4p_failover_config)

    def test_update_vol_stats_retest_u4p(self):
        self.rest.u4p_in_failover = True
        self.rest.u4p_failover_autofailback = True
        with mock.patch.object(
                self.common, 'retest_primary_u4p') as mock_retest:
            self.common.update_volume_stats()
            mock_retest.assert_called_once()

        self.rest.u4p_in_failover = True
        self.rest.u4p_failover_autofailback = False
        with mock.patch.object(
                self.common, 'retest_primary_u4p') as mock_retest:
            self.common.update_volume_stats()
            mock_retest.assert_not_called()

    @mock.patch.object(rest.PowerMaxRest, 'request', return_value=[200, None])
    @mock.patch.object(
        common.PowerMaxCommon, 'get_attributes_from_cinder_config',
        return_value=tpd.PowerMaxData.u4p_failover_target[0])
    def test_retest_primary_u4p(self, mock_primary_u4p, mock_request):
        self.common.retest_primary_u4p()
        self.assertFalse(self.rest.u4p_in_failover)

    @mock.patch.object(rest.PowerMaxRest, 'is_vol_in_rep_session',
                       return_value=(None, False, None))
    @mock.patch.object(common.PowerMaxCommon, '_cleanup_device_snapvx')
    def test_extend_vol_validation_checks_success(self, mck_cleanup, mck_rep):
        volume = self.data.test_volume
        array = self.data.array
        device_id = self.data.device_id
        new_size = self.data.test_volume.size + 1
        extra_specs = self.data.extra_specs
        self.common._extend_vol_validation_checks(
            array, device_id, volume.name, extra_specs, volume.size, new_size)

    @mock.patch.object(rest.PowerMaxRest, 'is_vol_in_rep_session',
                       return_value=(None, False, None))
    @mock.patch.object(common.PowerMaxCommon, '_cleanup_device_snapvx')
    def test_extend_vol_val_check_no_device(self, mck_cleanup, mck_rep):
        volume = self.data.test_volume
        array = self.data.array
        device_id = None
        new_size = self.data.test_volume.size + 1
        extra_specs = self.data.extra_specs
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.common._extend_vol_validation_checks,
            array, device_id, volume.name, extra_specs, volume.size, new_size)

    @mock.patch.object(rest.PowerMaxRest, 'is_vol_in_rep_session',
                       return_value=(None, True, None))
    @mock.patch.object(common.PowerMaxCommon, '_cleanup_device_snapvx')
    def test_extend_vol_val_check_snap_src(self, mck_cleanup, mck_rep):
        volume = self.data.test_volume
        array = self.data.array
        device_id = self.data.device_id
        new_size = self.data.test_volume.size + 1
        extra_specs = deepcopy(self.data.extra_specs)
        self.common.next_gen = False
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.common._extend_vol_validation_checks,
            array, device_id, volume.name, extra_specs, volume.size, new_size)

    @mock.patch.object(rest.PowerMaxRest, 'is_vol_in_rep_session',
                       return_value=(None, False, None))
    @mock.patch.object(common.PowerMaxCommon, '_cleanup_device_snapvx')
    def test_extend_vol_val_check_wrong_size(self, mck_cleanup, mck_rep):
        volume = self.data.test_volume
        array = self.data.array
        device_id = self.data.device_id
        new_size = volume.size - 1
        extra_specs = self.data.extra_specs
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.common._extend_vol_validation_checks,
            array, device_id, volume.name, extra_specs, volume.size, new_size)

    def test_array_ode_capabilities_check_non_next_gen_local(self):
        """Rep enabled, neither array next gen, returns F,F,F,F"""
        array = self.data.powermax_model_details['symmetrixId']
        self.common.next_gen = False
        (r1_ode, r1_ode_metro,
         r2_ode, r2_ode_metro) = self.common._array_ode_capabilities_check(
            array, self.data.rep_config_metro, True)
        self.assertFalse(r1_ode)
        self.assertFalse(r1_ode_metro)
        self.assertFalse(r2_ode)
        self.assertFalse(r2_ode_metro)

    @mock.patch.object(rest.PowerMaxRest, 'get_array_detail',
                       return_value={'ucode': '5977.1.1'})
    @mock.patch.object(common.PowerMaxCommon, 'get_rdf_details',
                       return_value=(10, tpd.PowerMaxData.remote_array))
    def test_array_ode_capabilities_check_next_gen_non_rep_pre_elm(
            self, mock_rdf, mock_det):
        """Rep disabled, local array next gen, pre elm, returns T,F,F,F"""
        array = self.data.powermax_model_details['symmetrixId']
        self.common.ucode_level = '5978.1.1'
        self.common.next_gen = True
        (r1_ode, r1_ode_metro,
         r2_ode, r2_ode_metro) = self.common._array_ode_capabilities_check(
            array, self.data.rep_config_metro, False)
        self.assertTrue(r1_ode)
        self.assertFalse(r1_ode_metro)
        self.assertFalse(r2_ode)
        self.assertFalse(r2_ode_metro)

    @mock.patch.object(rest.PowerMaxRest, 'get_array_detail',
                       return_value={'ucode': '5977.1.1'})
    @mock.patch.object(common.PowerMaxCommon, 'get_rdf_details',
                       return_value=(10, tpd.PowerMaxData.remote_array))
    def test_array_ode_capabilities_check_next_gen_remote_rep(
            self, mock_rdf, mock_det):
        """Rep enabled, remote not next gen, returns T,T,F,F"""
        array = self.data.powermax_model_details['symmetrixId']
        self.common.ucode_level = self.data.powermax_model_details['ucode']
        self.common.next_gen = True
        (r1_ode, r1_ode_metro,
         r2_ode, r2_ode_metro) = self.common._array_ode_capabilities_check(
            array, self.data.rep_config_metro, True)
        self.assertTrue(r1_ode)
        self.assertTrue(r1_ode_metro)
        self.assertFalse(r2_ode)
        self.assertFalse(r2_ode_metro)

    @mock.patch.object(rest.PowerMaxRest, 'get_array_detail',
                       return_value={'ucode': '5978.1.1'})
    @mock.patch.object(common.PowerMaxCommon, 'get_rdf_details',
                       return_value=(10, tpd.PowerMaxData.remote_array))
    def test_array_ode_capabilities_check_next_gen_pre_elm_rep(
            self, mock_rdf, mock_det):
        """Rep enabled, both array next gen, tgt<5978.221, returns T,T,T,F"""
        array = self.data.powermax_model_details['symmetrixId']
        self.common.ucode_level = self.data.powermax_model_details['ucode']
        self.common.next_gen = True
        (r1_ode, r1_ode_metro,
         r2_ode, r2_ode_metro) = self.common._array_ode_capabilities_check(
            array, self.data.rep_config_metro, True)
        self.assertTrue(r1_ode)
        self.assertTrue(r1_ode_metro)
        self.assertTrue(r2_ode)
        self.assertFalse(r2_ode_metro)

    @mock.patch.object(rest.PowerMaxRest, 'get_array_detail',
                       return_value=tpd.PowerMaxData.ucode_5978_foxtail)
    @mock.patch.object(common.PowerMaxCommon, 'get_rdf_details',
                       return_value=(10, tpd.PowerMaxData.remote_array))
    def test_array_ode_capabilities_check_next_gen_post_elm_rep(
            self, mock_rdf, mock_det):
        """Rep enabled, both array next gen, tgt>5978.221 returns T,T,T,T"""
        array = self.data.powermax_model_details['symmetrixId']
        self.common.ucode_level = self.data.powermax_model_details['ucode']
        self.common.next_gen = True
        (r1_ode, r1_ode_metro,
         r2_ode, r2_ode_metro) = self.common._array_ode_capabilities_check(
            array, self.data.rep_config_metro, True)
        self.assertTrue(r1_ode)
        self.assertTrue(r1_ode_metro)
        self.assertTrue(r2_ode)
        self.assertTrue(r2_ode_metro)

    @mock.patch.object(rest.PowerMaxRest, 'srdf_resume_replication')
    @mock.patch.object(common.PowerMaxCommon, '_protect_storage_group')
    @mock.patch.object(
        common.PowerMaxCommon, 'configure_volume_replication',
        return_value=('first_vol_in_rdf_group', None, None,
                      tpd.PowerMaxData.rep_extra_specs_mgmt, True))
    @mock.patch.object(provision.PowerMaxProvision, 'extend_volume')
    @mock.patch.object(common.PowerMaxCommon, 'break_rdf_device_pair_session')
    def test_extend_legacy_replicated_vol(
            self, mck_break, mck_extend, mck_configure, mck_protect, mck_res):
        volume = self.data.test_volume_group_member
        array = self.data.array
        device_id = self.data.device_id
        new_size = volume.size + 1
        extra_specs = self.data.extra_specs
        rdf_group_no = self.data.rdf_group_no_1
        self.common._extend_legacy_replicated_vol(
            array, volume, device_id, volume.name, new_size, extra_specs,
            rdf_group_no)
        mck_protect.assert_called_once()
        mck_res.assert_called_once()

    @mock.patch.object(
        common.PowerMaxCommon, 'break_rdf_device_pair_session',
        side_effect=exception.VolumeBackendAPIException)
    def test_extend_legacy_replicated_vol_fail(self, mck_resume):
        volume = self.data.test_volume_group_member
        array = self.data.array
        device_id = self.data.device_id
        new_size = volume.size + 1
        extra_specs = self.data.extra_specs
        rdf_group_no = self.data.rdf_group_no_1
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.common._extend_legacy_replicated_vol,
            array, device_id, volume.name, extra_specs, volume.size, new_size,
            rdf_group_no)

    def test_get_unisphere_port(self):
        # Test user set port ID
        configuration = tpfo.FakeConfiguration(
            None, 'CommonTests', 1, 1, san_ip='1.1.1.1', san_login='smc',
            powermax_array=self.data.array, powermax_srp='SRP_1',
            san_password='smc', san_api_port=1234,
            powermax_port_groups=[self.data.port_group_name_i])
        self.common.configuration = configuration
        port = self.common._get_unisphere_port()
        self.assertEqual(1234, port)

        # Test no set port ID, use default port
        configuration = tpfo.FakeConfiguration(
            None, 'CommonTests', 1, 1, san_ip='1.1.1.1', san_login='smc',
            powermax_array=self.data.array, powermax_srp='SRP_1',
            san_password='smc',
            powermax_port_groups=[self.data.port_group_name_i])
        self.common.configuration = configuration
        ref_port = utils.DEFAULT_PORT
        port = self.common._get_unisphere_port()
        self.assertEqual(ref_port, port)

    @mock.patch.object(rest.PowerMaxRest, 'find_snap_vx_sessions',
                       return_value=(None, tpd.PowerMaxData.snap_tgt_session))
    @mock.patch.object(rest.PowerMaxRest, 'is_vol_in_rep_session',
                       return_value=(True, False, False))
    def test_get_target_source_device(self, mck_rep, mck_find):
        array = self.data.array
        tgt_device = self.data.device_id2
        src_device = self.common._get_target_source_device(array, tgt_device)
        self.assertEqual(src_device, self.data.device_id)

    @mock.patch.object(rest.PowerMaxRest, '_get_private_volume',
                       return_value=tpd.PowerMaxData.priv_vol_response_rep)
    @mock.patch.object(rest.PowerMaxRest, 'get_array_model_info',
                       return_value=(tpd.PowerMaxData.array_model, None))
    @mock.patch.object(rest.PowerMaxRest, 'get_rdf_group',
                       return_value=(tpd.PowerMaxData.rdf_group_details))
    def test_get_volume_metadata_rep(self, mck_rdf, mck_model, mck_priv):
        ref_metadata = {
            'DeviceID': self.data.device_id,
            'DeviceLabel': self.data.device_label, 'ArrayID': self.data.array,
            'ArrayModel': self.data.array_model, 'ServiceLevel': 'None',
            'Workload': 'None', 'Emulation': 'FBA', 'Configuration': 'TDEV',
            'CompressionDisabled': 'True', 'ReplicationEnabled': 'True',
            'R2-DeviceID': self.data.device_id2,
            'R2-ArrayID': self.data.remote_array,
            'R2-ArrayModel': self.data.array_model,
            'ReplicationMode': 'Synchronized',
            'RDFG-Label': self.data.rdf_group_name_1,
            'R1-RDFG': 1, 'R2-RDFG': 1}
        array = self.data.array
        device_id = self.data.device_id
        act_metadata = self.common.get_volume_metadata(array, device_id)
        self.assertEqual(ref_metadata, act_metadata)

    @mock.patch.object(rest.PowerMaxRest, '_get_private_volume',
                       return_value=tpd.PowerMaxData.
                       priv_vol_response_metro_active_rep)
    @mock.patch.object(rest.PowerMaxRest, 'get_array_model_info',
                       return_value=(tpd.PowerMaxData.array_model, None))
    @mock.patch.object(rest.PowerMaxRest, 'get_rdf_group',
                       return_value=(tpd.PowerMaxData.rdf_group_details))
    def test_get_volume_metadata_metro_active_rep(self, mck_rdf,
                                                  mck_model, mck_priv):
        ref_metadata = {
            'DeviceID': self.data.device_id,
            'DeviceLabel': self.data.device_label, 'ArrayID': self.data.array,
            'ArrayModel': self.data.array_model, 'ServiceLevel': 'None',
            'Workload': 'None', 'Emulation': 'FBA', 'Configuration': 'TDEV',
            'CompressionDisabled': 'True', 'ReplicationEnabled': 'True',
            'R2-DeviceID': self.data.device_id2,
            'R2-ArrayID': self.data.remote_array,
            'R2-ArrayModel': self.data.array_model,
            'ReplicationMode': 'Metro',
            'RDFG-Label': self.data.rdf_group_name_1,
            'R1-RDFG': 1, 'R2-RDFG': 1}
        array = self.data.array
        device_id = self.data.device_id
        act_metadata = self.common.get_volume_metadata(array, device_id)
        self.assertEqual(ref_metadata, act_metadata)

    @mock.patch.object(rest.PowerMaxRest, '_get_private_volume',
                       return_value=tpd.PowerMaxData.priv_vol_response_no_rep)
    @mock.patch.object(rest.PowerMaxRest, 'get_array_model_info',
                       return_value=(tpd.PowerMaxData.array_model, None))
    def test_get_volume_metadata_no_rep(self, mck_model, mck_priv):
        ref_metadata = {
            'DeviceID': self.data.device_id,
            'DeviceLabel': self.data.device_label, 'ArrayID': self.data.array,
            'ArrayModel': self.data.array_model, 'ServiceLevel': 'None',
            'Workload': 'None', 'Emulation': 'FBA', 'Configuration': 'TDEV',
            'CompressionDisabled': 'True', 'ReplicationEnabled': 'False'}
        array = self.data.array
        device_id = self.data.device_id
        act_metadata = self.common.get_volume_metadata(array, device_id)
        self.assertEqual(ref_metadata, act_metadata)

    @mock.patch.object(rest.PowerMaxRest, 'get_volume_snap_info',
                       return_value=tpd.PowerMaxData.priv_snap_response)
    def test_get_snapshot_metadata(self, mck_snap):
        array = self.data.array
        device_id = self.data.device_id
        device_label = self.data.managed_snap_id
        snap_name = self.data.test_snapshot_snap_name
        ref_metadata = {'SnapshotLabel': snap_name,
                        'SourceDeviceID': device_id,
                        'SourceDeviceLabel': device_label,
                        'SnapIdList': six.text_type(self.data.snap_id),
                        'is_snap_id': True}

        act_metadata = self.common.get_snapshot_metadata(
            array, device_id, snap_name)
        self.assertEqual(ref_metadata, act_metadata)

    @mock.patch.object(
        rest.PowerMaxRest, 'get_volume_snap_info',
        return_value=(tpd.PowerMaxData.priv_snap_response_no_label))
    def test_get_snapshot_metadata_no_label(self, mck_snap):
        array = self.data.array
        device_id = self.data.device_id
        snap_name = self.data.test_snapshot_snap_name
        ref_metadata = {'SnapshotLabel': snap_name,
                        'SourceDeviceID': device_id,
                        'SnapIdList': six.text_type(self.data.snap_id),
                        'is_snap_id': True}

        act_metadata = self.common.get_snapshot_metadata(
            array, device_id, snap_name)
        self.assertEqual(ref_metadata, act_metadata)

    def test_update_metadata(self):
        model_update = {'provider_location': six.text_type(
            self.data.provider_location)}
        ref_model_update = (
            {'provider_location': six.text_type(self.data.provider_location),
             'metadata': {'device-meta-key-1': 'device-meta-value-1',
                          'device-meta-key-2': 'device-meta-value-2',
                          'user-meta-key-1': 'user-meta-value-1',
                          'user-meta-key-2': 'user-meta-value-2'}})

        existing_metadata = {'user-meta-key-1': 'user-meta-value-1',
                             'user-meta-key-2': 'user-meta-value-2'}

        object_metadata = {'device-meta-key-1': 'device-meta-value-1',
                           'device-meta-key-2': 'device-meta-value-2'}

        model_update = self.common.update_metadata(
            model_update, existing_metadata, object_metadata)
        self.assertEqual(ref_model_update, model_update)

    def test_update_metadata_no_model(self):
        model_update = None
        ref_model_update = (
            {'metadata': {'device-meta-key-1': 'device-meta-value-1',
                          'device-meta-key-2': 'device-meta-value-2',
                          'user-meta-key-1': 'user-meta-value-1',
                          'user-meta-key-2': 'user-meta-value-2'}})

        existing_metadata = {'user-meta-key-1': 'user-meta-value-1',
                             'user-meta-key-2': 'user-meta-value-2'}

        object_metadata = {'device-meta-key-1': 'device-meta-value-1',
                           'device-meta-key-2': 'device-meta-value-2'}

        model_update = self.common.update_metadata(
            model_update, existing_metadata, object_metadata)
        self.assertEqual(ref_model_update, model_update)

    def test_update_metadata_no_existing_metadata(self):
        model_update = {'provider_location': six.text_type(
            self.data.provider_location)}
        ref_model_update = (
            {'provider_location': six.text_type(self.data.provider_location),
             'metadata': {'device-meta-key-1': 'device-meta-value-1',
                          'device-meta-key-2': 'device-meta-value-2'}})

        existing_metadata = None

        object_metadata = {'device-meta-key-1': 'device-meta-value-1',
                           'device-meta-key-2': 'device-meta-value-2'}

        model_update = self.common.update_metadata(
            model_update, existing_metadata, object_metadata)
        self.assertEqual(ref_model_update, model_update)

    def test_update_metadata_model_list_exception(self):
        model_update = [{'provider_location': six.text_type(
            self.data.provider_location)}]

        existing_metadata = None

        object_metadata = {'device-meta-key-1': 'device-meta-value-1',
                           'device-meta-key-2': 'device-meta-value-2'}

        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.common.update_metadata, model_update, existing_metadata,
            object_metadata)

    def test_remove_stale_data(self):
        ret_model_update = self.common.remove_stale_data(
            self.data.replication_model)
        self.assertEqual(self.data.non_replication_model, ret_model_update)

    @mock.patch.object(rest.PowerMaxRest, 'get_storage_group',
                       return_value=tpd.PowerMaxData.add_volume_sg_info_dict)
    def test_get_tags_of_storage_group_none(self, mock_sg):
        self.assertIsNone(self.common.get_tags_of_storage_group(
            self.data.array, self.data.defaultstoragegroup_name))

    @mock.patch.object(rest.PowerMaxRest, 'get_storage_group',
                       return_value=tpd.PowerMaxData.storage_group_with_tags)
    def test_get_tags_of_storage_group_exists(self, mock_sg):
        tag_list = self.common.get_tags_of_storage_group(
            self.data.array, self.data.defaultstoragegroup_name)
        self.assertEqual(tpd.PowerMaxData.sg_tags, tag_list)

    @mock.patch.object(rest.PowerMaxRest, 'get_storage_group',
                       side_effect=exception.APIException)
    def test_get_tags_of_storage_group_exception(self, mock_sg):
        self.assertIsNone(self.common.get_tags_of_storage_group(
            self.data.array, self.data.storagegroup_name_f))

    @mock.patch.object(rest.PowerMaxRest, 'add_storage_array_tags')
    @mock.patch.object(rest.PowerMaxRest, 'get_array_tags',
                       return_value=[])
    def test_check_and_add_tags_to_storage_array(
            self, mock_get_tags, mock_add_tags):
        array_tag_list = ['OpenStack']
        self.common._check_and_add_tags_to_storage_array(
            self.data.array, array_tag_list, self.data.extra_specs)
        mock_add_tags.assert_called_with(
            self.data.array, array_tag_list, self.data.extra_specs)

    @mock.patch.object(rest.PowerMaxRest, 'add_storage_array_tags')
    @mock.patch.object(rest.PowerMaxRest, 'get_array_tags',
                       return_value=[])
    def test_check_and_add_tags_to_storage_array_add_2_tags(
            self, mock_get_tags, mock_add_tags):
        array_tag_list = ['OpenStack', 'Production']
        self.common._check_and_add_tags_to_storage_array(
            self.data.array, array_tag_list, self.data.extra_specs)
        mock_add_tags.assert_called_with(
            self.data.array, array_tag_list, self.data.extra_specs)

    @mock.patch.object(rest.PowerMaxRest, 'add_storage_array_tags')
    @mock.patch.object(rest.PowerMaxRest, 'get_array_tags',
                       return_value=['Production'])
    def test_check_and_add_tags_to_storage_array_add_1_tags(
            self, mock_get_tags, mock_add_tags):
        array_tag_list = ['OpenStack', 'Production']
        add_tag_list = ['OpenStack']
        self.common._check_and_add_tags_to_storage_array(
            self.data.array, array_tag_list, self.data.extra_specs)
        mock_add_tags.assert_called_with(
            self.data.array, add_tag_list, self.data.extra_specs)

    @mock.patch.object(rest.PowerMaxRest, 'add_storage_array_tags')
    @mock.patch.object(rest.PowerMaxRest, 'get_array_tags',
                       return_value=['openstack'])
    def test_check_and_add_tags_to_storage_array_already_tagged(
            self, mock_get_tags, mock_add_tags):
        array_tag_list = ['OpenStack']
        self.common._check_and_add_tags_to_storage_array(
            self.data.array, array_tag_list, self.data.extra_specs)
        mock_add_tags.assert_not_called()

    @mock.patch.object(rest.PowerMaxRest, 'get_array_tags',
                       return_value=[])
    def test_check_and_add_tags_to_storage_array_invalid_tag(
            self, mock_get_tags):
        array_tag_list = ['Open$tack']
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.common._check_and_add_tags_to_storage_array,
            self.data.array, array_tag_list, self.data.extra_specs)

    def test_validate_storage_group_tag_list_good_tag_list(self):
        self.common._validate_storage_group_tag_list(
            self.data.vol_type_extra_specs_tags)

    @mock.patch.object(utils.PowerMaxUtils, 'verify_tag_list')
    def test_validate_storage_group_tag_list_no_tag_list(
            self, mock_verify):
        self.common._validate_storage_group_tag_list(
            self.data.extra_specs)
        mock_verify.assert_not_called()

    def test_set_config_file_and_get_extra_specs(self):
        self.common.rep_config = {
            'mode': utils.REP_METRO, utils.METROBIAS: True}
        with mock.patch.object(self.utils, 'get_volumetype_extra_specs',
                               return_value=self.data.rep_extra_specs_metro):
            extra_specs, __ = self.common._set_config_file_and_get_extra_specs(
                self.data.test_volume, None)
            self.assertEqual(self.data.rep_extra_specs_metro, extra_specs)

    @mock.patch.object(utils.PowerMaxUtils, 'get_rdf_management_group_name')
    def test_retype_volume_promotion_get_extra_specs_mgmt_group(self, mck_get):
        array = self.data.array
        srp = self.data.srp
        device_id = self.data.device_id
        volume = self.data.test_volume
        volume_name = self.data.volume_id
        extra_specs = deepcopy(self.data.rep_extra_specs)
        target_slo = self.data.slo_silver
        target_workload = self.data.workload
        target_extra_specs = deepcopy(self.data.extra_specs)
        target_extra_specs[utils.DISABLECOMPRESSION] = False
        extra_specs[utils.REP_CONFIG] = self.data.rep_config_async
        self.common.promotion = True
        self.common._retype_volume(
            array, srp, device_id, volume, volume_name, extra_specs,
            target_slo, target_workload, target_extra_specs)
        self.common.promotion = False
        mck_get.assert_called_once_with(extra_specs[utils.REP_CONFIG])

    @mock.patch.object(rest.PowerMaxRest, 'is_volume_in_storagegroup',
                       return_value=True)
    @mock.patch.object(masking.PowerMaxMasking,
                       'return_volume_to_volume_group')
    @mock.patch.object(masking.PowerMaxMasking,
                       'move_volume_between_storage_groups')
    @mock.patch.object(
        masking.PowerMaxMasking, 'get_or_create_default_storage_group',
        return_value=tpd.PowerMaxData.rdf_managed_async_grp)
    @mock.patch.object(rest.PowerMaxRest, 'get_volume',
                       return_value=tpd.PowerMaxData.volume_details[0])
    @mock.patch.object(utils.PowerMaxUtils, 'get_rdf_management_group_name',
                       return_value=tpd.PowerMaxData.rdf_managed_async_grp)
    def test_retype_volume_detached(
            self, mck_get_rdf, mck_get_vol, mck_get_sg, mck_move_vol,
            mck_return_vol, mck_is_vol):

        array = self.data.array
        srp = self.data.srp
        device_id = self.data.device_id
        volume = self.data.test_volume
        volume_name = self.data.volume_id
        extra_specs = deepcopy(self.data.rep_extra_specs)
        target_slo = self.data.slo_silver
        target_workload = self.data.workload
        target_extra_specs = deepcopy(self.data.rep_extra_specs)
        target_extra_specs[utils.DISABLECOMPRESSION] = False
        group_name = self.data.rdf_managed_async_grp
        extra_specs[utils.REP_CONFIG] = self.data.rep_config_async
        target_extra_specs[utils.REP_CONFIG] = self.data.rep_config_async

        success, target_sg_name = self.common._retype_volume(
            array, srp, device_id, volume, volume_name, extra_specs,
            target_slo, target_workload, target_extra_specs, remote=True)

        mck_get_rdf.assert_called_once_with(self.data.rep_config_async)
        mck_get_vol.assert_called_once_with(array, device_id)
        mck_get_sg.assert_called_once_with(
            array, srp, target_slo, target_workload, extra_specs,
            False, True, target_extra_specs['rep_mode'])
        mck_move_vol.assert_called_once_with(
            array, device_id, self.data.volume_details[0]['storageGroupId'][0],
            group_name, extra_specs, force=True, parent_sg=None)
        mck_return_vol.assert_called_once_with(
            array, volume, device_id, volume_name, extra_specs)
        mck_is_vol.assert_called_once_with(array, device_id, group_name)
        self.assertTrue(success)
        self.assertEqual(group_name, target_sg_name)

    @mock.patch.object(
        utils.PowerMaxUtils, 'get_port_name_label',
        return_value='my_pg')
    @mock.patch.object(
        utils.PowerMaxUtils, 'get_volume_attached_hostname',
        return_value='HostX')
    @mock.patch.object(
        rest.PowerMaxRest, 'is_volume_in_storagegroup', return_value=True)
    @mock.patch.object(
        masking.PowerMaxMasking, 'return_volume_to_volume_group')
    @mock.patch.object(
        masking.PowerMaxMasking, 'move_volume_between_storage_groups')
    @mock.patch.object(
        masking.PowerMaxMasking, 'add_child_sg_to_parent_sg')
    @mock.patch.object(
        provision.PowerMaxProvision, 'create_storage_group')
    @mock.patch.object(
        rest.PowerMaxRest, 'get_storage_group',
        side_effect=[None, tpd.PowerMaxData.volume_info_dict])
    @mock.patch.object(
        rest.PowerMaxRest, 'get_volume',
        return_value=tpd.PowerMaxData.volume_details[0])
    @mock.patch.object(
        utils.PowerMaxUtils, 'get_rdf_management_group_name',
        return_value=tpd.PowerMaxData.rdf_managed_async_grp)
    def test_retype_volume_attached(
            self, mck_get_rdf, mck_get_vol, mck_get_sg, mck_create, mck_add,
            mck_move_vol, mck_return_vol, mck_is_vol, mck_host, mck_pg):

        array = self.data.array
        srp = self.data.srp
        device_id = self.data.device_id
        volume = self.data.test_attached_volume
        volume_name = self.data.volume_id
        extra_specs = self.data.rep_extra_specs_rep_config
        target_slo = self.data.slo_silver
        target_workload = self.data.workload
        target_extra_specs = deepcopy(self.data.rep_extra_specs)
        target_extra_specs[utils.DISABLECOMPRESSION] = False
        target_extra_specs[utils.REP_CONFIG] = self.data.rep_config_sync

        success, target_sg_name = self.common._retype_volume(
            array, srp, device_id, volume, volume_name, extra_specs,
            target_slo, target_workload, target_extra_specs)
        mck_get_rdf.assert_called_once()
        mck_get_vol.assert_called_once()
        mck_create.assert_called_once()
        mck_add.assert_called_once()
        mck_move_vol.assert_called_once()
        mck_return_vol.assert_called_once()
        mck_is_vol.assert_called_once()
        self.assertEqual(2, mck_get_sg.call_count)
        self.assertTrue(success)

    @mock.patch.object(
        utils.PowerMaxUtils, 'get_volume_attached_hostname', return_value=None)
    @mock.patch.object(
        rest.PowerMaxRest, 'get_volume',
        return_value=tpd.PowerMaxData.volume_details[0])
    @mock.patch.object(
        utils.PowerMaxUtils, 'get_rdf_management_group_name',
        return_value=tpd.PowerMaxData.rdf_managed_async_grp)
    def test_retype_volume_attached_no_host_fail(
            self, mck_get_rdf, mck_get_vol, mck_get_host):

        array = self.data.array
        srp = self.data.srp
        device_id = self.data.device_id
        volume = self.data.test_attached_volume
        volume_name = self.data.volume_id
        extra_specs = self.data.rep_extra_specs_rep_config
        target_slo = self.data.slo_silver
        target_workload = self.data.workload
        target_extra_specs = deepcopy(self.data.rep_extra_specs)
        target_extra_specs[utils.DISABLECOMPRESSION] = False
        target_extra_specs[utils.REP_CONFIG] = self.data.rep_config_async

        success, target_sg_name = self.common._retype_volume(
            array, srp, device_id, volume, volume_name, extra_specs,
            target_slo, target_workload, target_extra_specs)
        mck_get_rdf.assert_called_once()
        mck_get_vol.assert_called_once()
        self.assertFalse(success)
        self.assertIsNone(target_sg_name)

    @mock.patch.object(rest.PowerMaxRest, 'is_volume_in_storagegroup',
                       return_value=False)
    @mock.patch.object(masking.PowerMaxMasking,
                       'return_volume_to_volume_group')
    @mock.patch.object(masking.PowerMaxMasking,
                       'move_volume_between_storage_groups')
    @mock.patch.object(
        masking.PowerMaxMasking, 'get_or_create_default_storage_group',
        return_value=tpd.PowerMaxData.rdf_managed_async_grp)
    @mock.patch.object(rest.PowerMaxRest, 'get_volume',
                       return_value=tpd.PowerMaxData.volume_details[0])
    @mock.patch.object(utils.PowerMaxUtils, 'get_rdf_management_group_name',
                       return_value=tpd.PowerMaxData.rdf_managed_async_grp)
    def test_retype_volume_detached_vol_not_in_sg_fail(
            self, mck_get_rdf, mck_get_vol, mck_get_sg, mck_move_vol,
            mck_return_vol, mck_is_vol):

        array = self.data.array
        srp = self.data.srp
        device_id = self.data.device_id
        volume = self.data.test_volume
        volume_name = self.data.volume_id
        extra_specs = deepcopy(self.data.rep_extra_specs)
        target_slo = self.data.slo_silver
        target_workload = self.data.workload
        target_extra_specs = deepcopy(self.data.rep_extra_specs)
        target_extra_specs[utils.DISABLECOMPRESSION] = False
        extra_specs[utils.REP_CONFIG] = self.data.rep_config_async
        target_extra_specs[utils.REP_CONFIG] = self.data.rep_config_async

        success, target_sg_name = self.common._retype_volume(
            array, srp, device_id, volume, volume_name, extra_specs,
            target_slo, target_workload, target_extra_specs, remote=True)
        self.assertFalse(success)
        self.assertIsNone(target_sg_name)

    @mock.patch.object(
        rest.PowerMaxRest, 'rename_volume')
    @mock.patch.object(
        rest.PowerMaxRest, 'get_rdf_pair_volume',
        return_value=tpd.PowerMaxData.rdf_group_vol_details)
    def test_get_and_set_remote_device_uuid(self, mck_get_pair, mck_rename):
        extra_specs = self.data.rep_extra_specs
        rep_extra_specs = self.data.rep_extra_specs_mgmt
        volume_dict = {'device_id': self.data.device_id,
                       'device_uuid': self.data.volume_id}

        remote_vol = self.common.get_and_set_remote_device_uuid(
            extra_specs, rep_extra_specs, volume_dict)
        self.assertEqual(remote_vol, self.data.device_id2)

    @mock.patch.object(utils.PowerMaxUtils, 'get_volume_group_utils',
                       return_value=(None, {'interval': 1, 'retries': 1}))
    def test_get_volume_group_info(self, mock_group_utils):
        self.common.interval = 1
        self.common.retries = 1
        with mock.patch.object(
                tpfo.FakeConfiguration, 'safe_get') as mock_array:
            self.common._get_volume_group_info(
                self.data.test_group_1)
            mock_group_utils.assert_called_once_with(
                self.data.test_group_1, self.common.interval,
                self.common.retries)
            mock_array.assert_called_once()

    def test_get_performance_config(self):
        ref_cinder_conf = tpfo.FakeConfiguration(
            None, 'ProvisionTests', 1, 1, san_ip='1.1.1.1', san_login='smc',
            powermax_array=self.data.array, powermax_srp='SRP_1',
            san_password='smc', san_api_port=8443,
            powermax_port_groups=[self.data.port_group_name_f],
            load_balance=True, load_balance_real_time=True,
            load_data_format='avg', load_look_back=60,
            load_look_back_real_time=10, port_group_load_metric='PercentBusy',
            port_load_metric='PercentBusy')

        ref_perf_conf = self.data.performance_config
        volume_utils.get_max_over_subscription_ratio = mock.Mock()
        rest.PowerMaxRest._establish_rest_session = mock.Mock(
            return_value=tpfo.FakeRequestsSession())
        driver = fc.PowerMaxFCDriver(configuration=ref_cinder_conf)
        self.assertEqual(ref_perf_conf, driver.common.performance.config)

    def test_select_port_group_for_extra_specs_volume_type(self):
        """Test _select_port_group_for_extra_specs PG in volume-type."""
        extra_specs = {utils.PORTGROUPNAME: self.data.port_group_name_i}
        pool_record = {}
        port_group = self.common._select_port_group_for_extra_specs(
            extra_specs, pool_record)
        self.assertEqual(self.data.port_group_name_i, port_group)

    def test_select_port_group_for_extra_specs_cinder_conf_single(self):
        """Test _select_port_group_for_extra_specs single PG in cinder conf."""
        extra_specs = {}
        pool_record = {utils.PORT_GROUP: [self.data.port_group_name_i]}
        port_group = self.common._select_port_group_for_extra_specs(
            extra_specs, pool_record)
        self.assertEqual(self.data.port_group_name_i, port_group)

    def test_select_port_group_for_extra_specs_cinder_conf_multi(self):
        """Test _select_port_group_for_extra_specs multi PG in cinder conf.

        Random selection is used, no performance configuration supplied.
        """
        extra_specs = {}
        pool_record = {utils.PORT_GROUP: self.data.perf_port_groups}
        port_group = self.common._select_port_group_for_extra_specs(
            extra_specs, pool_record)
        self.assertIn(port_group, self.data.perf_port_groups)

    def test_select_port_group_for_extra_specs_load_balanced(self):
        """Test _select_port_group_for_extra_specs multi PG in cinder conf.

        Load balanced selection is used, performance configuration supplied.
        """
        extra_specs = {utils.ARRAY: self.data.array}
        pool_record = {utils.PORT_GROUP: self.data.perf_port_groups}
        self.common.performance.config = self.data.performance_config
        with mock.patch.object(
                self.common.performance, 'process_port_group_load',
                side_effect=(
                    self.common.performance.process_port_group_load)) as (
                        mck_process):
            port_group = self.common._select_port_group_for_extra_specs(
                extra_specs, pool_record, init_conn=True)
            mck_process.assert_called_once_with(
                self.data.array, self.data.perf_port_groups)
            self.assertIn(port_group, self.data.perf_port_groups)

    def test_select_port_group_for_extra_specs_exception(self):
        """Test _select_port_group_for_extra_specs exception."""
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.common._select_port_group_for_extra_specs, {}, {})

    @mock.patch.object(
        common.PowerMaxCommon, '_add_new_volume_to_volume_group',
        return_value='my_group')
    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                       return_value=True)
    def test_add_to_group(self, mock_cond, mock_group):
        source_volume = self.data.test_volume
        extra_specs = self.data.extra_specs
        rep_driver_data = dict()
        group_name = self.common._add_to_group(
            source_volume, self.data, source_volume.name,
            self.data.test_group_1.fields.get('id'), self.data.test_group_1,
            extra_specs, rep_driver_data)
        self.assertEqual('my_group', group_name)
        mock_group.assert_called_once()

    @mock.patch.object(
        common.PowerMaxCommon, '_add_new_volume_to_volume_group',
        return_value='my_group')
    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                       return_value=True)
    def test_add_to_group_no_group_obj(self, mock_cond, mock_group):
        source_volume = self.data.test_volume
        extra_specs = self.data.extra_specs
        rep_driver_data = dict()
        group_name = self.common._add_to_group(
            source_volume, self.data, source_volume.name,
            self.data.test_group_1.fields.get('id'), None, extra_specs,
            rep_driver_data)
        self.assertIsNone(group_name)
        mock_group.assert_not_called()

    @mock.patch.object(
        common.PowerMaxCommon, '_unlink_and_delete_temporary_snapshots')
    @mock.patch.object(rest.PowerMaxRest, 'find_snap_vx_sessions',
                       return_value=(None, 'tgt_session'))
    @mock.patch.object(rest.PowerMaxRest, 'is_vol_in_rep_session',
                       return_value=(True, False, False))
    def test_cleanup_device_snapvx(self, mck_is_rep, mck_find, mck_unlink):
        array = self.data.array
        device_id = self.data.device_id
        extra_specs = self.data.extra_specs
        self.common._cleanup_device_snapvx(array, device_id, extra_specs)
        mck_unlink.assert_called_once_with('tgt_session', array, extra_specs)

    @mock.patch.object(
        common.PowerMaxCommon, '_unlink_and_delete_temporary_snapshots')
    @mock.patch.object(rest.PowerMaxRest, 'is_vol_in_rep_session',
                       return_value=(False, False, False))
    def test_cleanup_device_snapvx_no_sessions(self, mck_is_rep, mck_unlink):
        array = self.data.array
        device_id = self.data.device_id
        extra_specs = self.data.extra_specs
        self.common._cleanup_device_snapvx(array, device_id, extra_specs)
        mck_unlink.assert_not_called()

    @mock.patch.object(common.PowerMaxCommon, '_delete_temp_snapshot')
    @mock.patch.object(common.PowerMaxCommon, '_unlink_snapshot',
                       return_value=True)
    def test_unlink_and_delete_temporary_snapshots_session_unlinked(
            self, mck_unlink, mck_delete):
        session = self.data.snap_tgt_session
        array = self.data.array
        extra_specs = self.data.extra_specs
        self.common._unlink_and_delete_temporary_snapshots(
            session, array, extra_specs)
        mck_unlink.assert_called_once_with(session, array, extra_specs)
        mck_delete.assert_called_once_with(session, array)

    @mock.patch.object(common.PowerMaxCommon, '_delete_temp_snapshot')
    @mock.patch.object(common.PowerMaxCommon, '_unlink_snapshot',
                       return_value=False)
    def test_unlink_and_delete_temporary_snapshots_session_not_unlinked(
            self, mck_unlink, mck_delete):
        session = self.data.snap_tgt_session
        array = self.data.array
        extra_specs = self.data.extra_specs
        self.common._unlink_and_delete_temporary_snapshots(
            session, array, extra_specs)
        mck_unlink.assert_called_once_with(session, array, extra_specs)
        mck_delete.assert_not_called()

    @mock.patch.object(provision.PowerMaxProvision, 'unlink_snapvx_tgt_volume')
    @mock.patch.object(rest.PowerMaxRest, 'get_volume_snap',
                       side_effect=[tpd.PowerMaxData.priv_snap_response.get(
                           'snapshotSrcs')[0], None])
    def test_unlink_temp_snapshot(self, mck_get, mck_unlink):
        array = self.data.array
        extra_specs = self.data.extra_specs
        session = self.data.snap_tgt_session
        source = session.get('source_vol_id')
        target = session.get('target_vol_id')
        snap_name = session.get('snap_name')
        snap_id = session.get('snapid')
        loop = False
        is_unlinked = self.common._unlink_snapshot(session, array, extra_specs)
        mck_unlink.assert_called_once_with(
            array, target, source, snap_name, extra_specs, snap_id, loop)
        self.assertTrue(is_unlinked)

    @mock.patch.object(provision.PowerMaxProvision, 'unlink_snapvx_tgt_volume')
    @mock.patch.object(rest.PowerMaxRest, 'get_volume_snap',
                       return_value=tpd.PowerMaxData.priv_snap_response.get(
                           'snapshotSrcs')[0])
    def test_unlink_temp_snapshot_not_unlinked(self, mck_get, mck_unlink):
        array = self.data.array
        extra_specs = self.data.extra_specs
        session = self.data.snap_tgt_session
        source = session.get('source_vol_id')
        target = session.get('target_vol_id')
        snap_name = session.get('snap_name')
        snap_id = session.get('snapid')
        loop = False
        is_unlinked = self.common._unlink_snapshot(session, array, extra_specs)
        mck_unlink.assert_called_once_with(
            array, target, source, snap_name, extra_specs, snap_id, loop)
        self.assertFalse(is_unlinked)

    @mock.patch.object(provision.PowerMaxProvision, 'delete_temp_volume_snap')
    @mock.patch.object(rest.PowerMaxRest, 'get_volume_snap',
                       return_value=dict())
    def test_delete_temp_snapshot(self, mck_get, mck_delete):
        session = self.data.snap_tgt_session
        array = self.data.array
        snap_name = session.get('snap_name')
        source = session.get('source_vol_id')
        snap_id = session.get('snapid')
        self.common._delete_temp_snapshot(session, array)
        mck_delete.assert_called_once_with(array, snap_name, source, snap_id)

    @mock.patch.object(provision.PowerMaxProvision, 'delete_temp_volume_snap')
    @mock.patch.object(rest.PowerMaxRest, 'get_volume_snap',
                       return_value={'linkedDevices': 'details'})
    def test_delete_temp_snapshot_is_linked(self, mck_get, mck_delete):
        session = self.data.snap_tgt_session
        array = self.data.array
        self.common._delete_temp_snapshot(session, array)
        mck_delete.assert_not_called()
