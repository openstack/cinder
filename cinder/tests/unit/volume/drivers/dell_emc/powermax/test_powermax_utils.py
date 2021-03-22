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

from copy import deepcopy
import datetime
from unittest import mock

from ddt import data
from ddt import ddt
import six

from cinder import exception
from cinder.objects import fields
from cinder.tests.unit import test
from cinder.tests.unit.volume.drivers.dell_emc.powermax import (
    powermax_data as tpd)
from cinder.tests.unit.volume.drivers.dell_emc.powermax import (
    powermax_fake_objects as tpfo)
from cinder.volume.drivers.dell_emc.powermax import iscsi
from cinder.volume.drivers.dell_emc.powermax import rest
from cinder.volume.drivers.dell_emc.powermax import utils
from cinder.volume import volume_types
from cinder.volume import volume_utils


@ddt
class PowerMaxUtilsTest(test.TestCase):
    def setUp(self):
        self.data = tpd.PowerMaxData()
        volume_utils.get_max_over_subscription_ratio = mock.Mock()
        super(PowerMaxUtilsTest, self).setUp()
        self.replication_device = self.data.sync_rep_device
        configuration = tpfo.FakeConfiguration(
            None, 'UtilsTests', 1, 1, san_ip='1.1.1.1', san_login='smc',
            powermax_array=self.data.array, powermax_srp='SRP_1',
            san_password='smc', san_api_port=8443,
            powermax_port_groups=[self.data.port_group_name_i],
            replication_device=self.replication_device)
        rest.PowerMaxRest._establish_rest_session = mock.Mock(
            return_value=tpfo.FakeRequestsSession())
        driver = iscsi.PowerMaxISCSIDriver(configuration=configuration)
        self.driver = driver
        self.common = self.driver.common
        self.utils = self.common.utils

    def test_get_volumetype_extra_specs(self):
        with mock.patch.object(volume_types, 'get_volume_type_extra_specs',
                               return_value={'specs'}) as type_mock:
            # path 1: volume_type_id not passed in
            self.data.test_volume.volume_type_id = (
                self.data.test_volume_type.id)
            self.utils.get_volumetype_extra_specs(self.data.test_volume)
            type_mock.assert_called_once_with(self.data.test_volume_type.id)
            type_mock.reset_mock()
            # path 2: volume_type_id passed in
            self.utils.get_volumetype_extra_specs(self.data.test_volume, '123')
            type_mock.assert_called_once_with('123')
            type_mock.reset_mock()
            # path 3: no type_id
            self.utils.get_volumetype_extra_specs(self.data.test_clone_volume)
            type_mock.assert_not_called()

    def test_get_volumetype_extra_specs_exception(self):
        extra_specs = self.utils.get_volumetype_extra_specs(
            {'name': 'no_type_id'})
        self.assertEqual({}, extra_specs)

    def test_get_host_short_name(self):
        host_under_16_chars = 'host_13_chars'
        host1 = self.utils.get_host_short_name(
            host_under_16_chars)
        self.assertEqual(host_under_16_chars, host1)

        host_over_16_chars = (
            'host_over_16_chars_host_over_16_chars_host_over_16_chars')
        # Check that the same md5 value is retrieved from multiple calls
        host2 = self.utils.get_host_short_name(
            host_over_16_chars)
        host3 = self.utils.get_host_short_name(
            host_over_16_chars)
        self.assertEqual(host2, host3)
        host_with_period = 'hostname.with.many.parts'
        ref_host_name = self.utils.generate_unique_trunc_host('hostname')
        host4 = self.utils.get_host_short_name(host_with_period)
        self.assertEqual(ref_host_name, host4)

    def test_get_volume_element_name(self):
        volume_id = 'ea95aa39-080b-4f11-9856-a03acf9112ad'
        volume_element_name = self.utils.get_volume_element_name(volume_id)
        expect_vol_element_name = ('OS-' + volume_id)
        self.assertEqual(expect_vol_element_name, volume_element_name)

    def test_truncate_string(self):
        # string is less than max number
        str_to_truncate = 'string'
        response = self.utils.truncate_string(str_to_truncate, 10)
        self.assertEqual(str_to_truncate, response)

    def test_get_default_oversubscription_ratio(self):
        default_ratio = 20.0
        max_over_sub_ratio1 = 30.0
        returned_max = self.utils.get_default_oversubscription_ratio(
            max_over_sub_ratio1)
        self.assertEqual(max_over_sub_ratio1, returned_max)
        max_over_sub_ratio2 = 0.5
        returned_max = self.utils.get_default_oversubscription_ratio(
            max_over_sub_ratio2)
        self.assertEqual(default_ratio, returned_max)

    def test_get_default_storage_group_name_slo_workload(self):
        srp_name = self.data.srp
        slo = self.data.slo
        workload = self.data.workload
        sg_name = self.utils.get_default_storage_group_name(
            srp_name, slo, workload)
        self.assertEqual(self.data.defaultstoragegroup_name, sg_name)

    def test_get_default_storage_group_name_no_slo(self):
        srp_name = self.data.srp
        slo = None
        workload = None
        sg_name = self.utils.get_default_storage_group_name(
            srp_name, slo, workload)
        self.assertEqual(self.data.default_sg_no_slo, sg_name)

    def test_get_default_storage_group_name_compr_disabled(self):
        srp_name = self.data.srp
        slo = self.data.slo
        workload = self.data.workload
        sg_name = self.utils.get_default_storage_group_name(
            srp_name, slo, workload, True)
        self.assertEqual(self.data.default_sg_compr_disabled, sg_name)

    def test_get_time_delta(self):
        start_time = 1487781721.09
        end_time = 1487781758.16
        delta = end_time - start_time
        ref_delta = six.text_type(datetime.timedelta(seconds=int(delta)))
        time_delta = self.utils.get_time_delta(start_time, end_time)
        self.assertEqual(ref_delta, time_delta)

    def test_get_short_protocol_type(self):
        # iscsi
        short_i_protocol = self.utils.get_short_protocol_type('iscsi')
        self.assertEqual('I', short_i_protocol)
        # fc
        short_f_protocol = self.utils.get_short_protocol_type('FC')
        self.assertEqual('F', short_f_protocol)
        # else
        other_protocol = self.utils.get_short_protocol_type('OTHER')
        self.assertEqual('OTHER', other_protocol)

    def test_get_temp_snap_name(self):
        source_device_id = self.data.device_id
        ref_name = self.data.temp_snapvx
        snap_name = self.utils.get_temp_snap_name(source_device_id)
        self.assertEqual(ref_name, snap_name)

    def test_get_array_and_device_id(self):
        volume = deepcopy(self.data.test_volume)
        external_ref = {u'source-name': u'00002'}
        array, device_id = self.utils.get_array_and_device_id(
            volume, external_ref)
        self.assertEqual(self.data.array, array)
        self.assertEqual('00002', device_id)
        # Test to check if device id returned is in upper case
        external_ref = {u'source-name': u'0028a'}
        __, device_id = self.utils.get_array_and_device_id(
            volume, external_ref)
        ref_device_id = u'0028A'
        self.assertEqual(ref_device_id, device_id)

    def test_get_array_and_device_id_exception(self):
        volume = deepcopy(self.data.test_volume)
        external_ref = {u'source-name': None}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.utils.get_array_and_device_id,
                          volume, external_ref)

    @data({u'source-name': u'000001'}, {u'source-name': u'00028A'})
    def test_get_array_and_device_id_invalid_long_id(self, external_ref):
        volume = deepcopy(self.data.test_volume)
        # Test for device id more than 5 digits
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.utils.get_array_and_device_id,
                          volume, external_ref)

    @data({u'source-name': u'01'}, {u'source-name': u'028A'},
          {u'source-name': u'0001'})
    def test_get_array_and_device_id_invalid_short_id(self, external_ref):
        volume = deepcopy(self.data.test_volume)
        # Test for device id less than 5 digits
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.utils.get_array_and_device_id,
                          volume, external_ref)

    def test_get_pg_short_name(self):
        pg_under_12_chars = 'pg_11_chars'
        pg1 = self.utils.get_pg_short_name(pg_under_12_chars)
        self.assertEqual(pg_under_12_chars, pg1)

        pg_over_12_chars = 'portgroup_over_12_characters'
        # Check that the same md5 value is retrieved from multiple calls
        pg2 = self.utils.get_pg_short_name(pg_over_12_chars)
        pg3 = self.utils.get_pg_short_name(pg_over_12_chars)
        self.assertEqual(pg2, pg3)

    def test_is_compression_disabled_true(self):
        # Compression disabled in extra specs
        extra_specs = self.data.extra_specs_disable_compression
        self.assertTrue(self.utils.is_compression_disabled(extra_specs))
        # Compression disabled by no SL/WL combination
        extra_specs = deepcopy(self.data.vol_type_extra_specs_none_pool)
        self.assertTrue(self.utils.is_compression_disabled(extra_specs))
        extra_specs3 = deepcopy(extra_specs)
        extra_specs3.update({utils.DISABLECOMPRESSION: '<is> True'})
        self.assertTrue(self.utils.is_compression_disabled(extra_specs3))
        extra_specs4 = deepcopy(extra_specs)
        extra_specs4.update({utils.DISABLECOMPRESSION: 'True'})
        self.assertTrue(self.utils.is_compression_disabled(extra_specs4))

    def test_is_compression_disabled_false(self):
        # Path 1: no compression extra spec set
        extra_specs = self.data.extra_specs
        self.assertFalse(self.utils.is_compression_disabled(extra_specs))
        # Path 2: compression extra spec set to false
        extra_specs2 = deepcopy(extra_specs)
        extra_specs2.update({utils.DISABLECOMPRESSION: 'false'})
        self.assertFalse(self.utils.is_compression_disabled(extra_specs2))
        extra_specs3 = deepcopy(extra_specs)
        extra_specs3.update({utils.DISABLECOMPRESSION: '<is> False'})
        self.assertFalse(self.utils.is_compression_disabled(extra_specs3))
        extra_specs4 = deepcopy(extra_specs)
        extra_specs4.update({utils.DISABLECOMPRESSION: 'False'})
        self.assertFalse(self.utils.is_compression_disabled(extra_specs4))

    def test_change_compression_type_true(self):
        source_compr_disabled = True
        new_type_compr_disabled_1 = {
            'extra_specs': {utils.DISABLECOMPRESSION: 'false'}}
        self.assertTrue(self.utils.change_compression_type(
            source_compr_disabled, new_type_compr_disabled_1))
        new_type_compr_disabled_2 = {
            'extra_specs': {utils.DISABLECOMPRESSION: '<is> False'}}
        self.assertTrue(self.utils.change_compression_type(
            source_compr_disabled, new_type_compr_disabled_2))

    def test_change_compression_type_false(self):
        source_compr_disabled = True
        new_type_compr_disabled = {
            'extra_specs': {utils.DISABLECOMPRESSION: 'true'}}
        self.assertFalse(self.utils.change_compression_type(
            source_compr_disabled, new_type_compr_disabled))
        new_type_compr_disabled_2 = {
            'extra_specs': {utils.DISABLECOMPRESSION: '<is> True'}}
        self.assertFalse(self.utils.change_compression_type(
            source_compr_disabled, new_type_compr_disabled_2))

    def test_is_replication_enabled(self):
        is_re = self.utils.is_replication_enabled(
            self.data.vol_type_extra_specs_rep_enabled)
        self.assertTrue(is_re)
        is_re2 = self.utils.is_replication_enabled(self.data.extra_specs)
        self.assertFalse(is_re2)

    def test_get_replication_config(self):
        # Success, allow_extend false
        rep_device_list1 = [{'target_device_id': self.data.remote_array,
                             'remote_pool': self.data.srp,
                             'remote_port_group': self.data.port_group_name_f,
                             'rdf_group_label': self.data.rdf_group_name_1}]
        rep_config1 = self.utils.get_replication_config(rep_device_list1)[0]
        self.assertEqual(self.data.remote_array, rep_config1['array'])
        # Success, allow_extend true
        rep_device_list2 = rep_device_list1
        rep_device_list2[0]['allow_extend'] = 'true'
        rep_config2 = self.utils.get_replication_config(rep_device_list2)[0]
        self.assertTrue(rep_config2['allow_extend'])
        # No rep_device_list
        rep_device_list3 = []
        rep_config3 = self.utils.get_replication_config(rep_device_list3)
        self.assertIsNone(rep_config3)
        # Exception
        rep_device_list4 = [{'target_device_id': self.data.remote_array,
                             'remote_pool': self.data.srp}]
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.utils.get_replication_config, rep_device_list4)
        # Success, mode is async
        rep_device_list5 = rep_device_list2
        rep_device_list5[0]['mode'] = 'async'
        rep_config5 = self.utils.get_replication_config(rep_device_list5)[0]
        self.assertEqual(utils.REP_ASYNC, rep_config5['mode'])
        # Success, mode is metro - no other options set
        rep_device_list6 = rep_device_list5
        rep_device_list6[0]['mode'] = 'metro'
        rep_config6 = self.utils.get_replication_config(rep_device_list6)[0]
        self.assertFalse(rep_config6['metro_bias'])
        # Success, mode is metro - metro options true
        rep_device_list7 = rep_device_list6
        rep_device_list7[0].update({'metro_use_bias': 'true'})
        rep_config7 = self.utils.get_replication_config(rep_device_list7)[0]
        self.assertTrue(rep_config7['metro_bias'])
        # Success, no backend id
        self.assertIsNone(rep_config7.get(utils.BACKEND_ID))
        # Success, backend id
        rep_device_list8 = rep_device_list6
        rep_device_list8[0].update(
            {utils.BACKEND_ID: self.data.rep_backend_id_sync})
        rep_config8 = self.utils.get_replication_config(rep_device_list8)[0]
        self.assertEqual(
            self.data.rep_backend_id_sync, rep_config8[utils.BACKEND_ID])
        # Success, multi-rep
        multi_rep_device_list = self.data.multi_rep_device
        multi_rep_config = self.utils.get_replication_config(
            multi_rep_device_list)
        self.assertTrue(len(multi_rep_config) > 1)
        for rep_config in multi_rep_config:
            self.assertEqual(rep_config['array'], self.data.remote_array)

    def test_get_replication_config_sync_retries_intervals(self):
        # Default sync interval & retry values
        rep_device_list1 = [{'target_device_id': self.data.remote_array,
                             'remote_pool': self.data.srp,
                             'remote_port_group': self.data.port_group_name_f,
                             'rdf_group_label': self.data.rdf_group_name_1}]

        rep_config1 = self.utils.get_replication_config(rep_device_list1)[0]
        self.assertEqual(200, rep_config1['sync_retries'])
        self.assertEqual(3, rep_config1['sync_interval'])

        # User set interval & retry values
        rep_device_list2 = deepcopy(rep_device_list1)
        rep_device_list2[0].update({'sync_retries': 300, 'sync_interval': 1})
        rep_config2 = self.utils.get_replication_config(rep_device_list2)[0]
        self.assertEqual(300, rep_config2['sync_retries'])
        self.assertEqual(1, rep_config2['sync_interval'])

    def test_is_volume_failed_over(self):
        vol = deepcopy(self.data.test_volume)
        vol.replication_status = fields.ReplicationStatus.FAILED_OVER
        is_fo1 = self.utils.is_volume_failed_over(vol)
        self.assertTrue(is_fo1)
        is_fo2 = self.utils.is_volume_failed_over(self.data.test_volume)
        self.assertFalse(is_fo2)
        is_fo3 = self.utils.is_volume_failed_over(None)
        self.assertFalse(is_fo3)

    def test_add_legacy_pools(self):
        pools = [{'pool_name': 'Diamond+None+SRP_1+000197800111'},
                 {'pool_name': 'Diamond+OLTP+SRP_1+000197800111'}]
        new_pools = self.utils.add_legacy_pools(pools)
        ref_pools = [{'pool_name': 'Diamond+None+SRP_1+000197800111'},
                     {'pool_name': 'Diamond+OLTP+SRP_1+000197800111'},
                     {'pool_name': 'Diamond+SRP_1+000197800111'}]
        self.assertEqual(ref_pools, new_pools)

    def test_add_promotion_pools(self):
        array = self.data.array
        pools = [{'pool_name': 'Diamond+None+SRP_1+000197800111',
                  'location_info': '000197800111#SRP_1#None#Diamond'},
                 {'pool_name': 'Gold+OLTP+SRP_1+000197800111',
                  'location_info': '000197800111#SRP_1#OLTP#Gold'}]
        new_pools = self.utils.add_promotion_pools(pools, array)
        ref_pools = [{'pool_name': 'Diamond+None+SRP_1+000197800111',
                      'location_info': '000197800111#SRP_1#None#Diamond'},
                     {'pool_name': 'Gold+OLTP+SRP_1+000197800111',
                      'location_info': '000197800111#SRP_1#OLTP#Gold'},
                     {'pool_name': 'Diamond+None+SRP_1+000197800123',
                      'location_info': '000197800123#SRP_1#None#Diamond'},
                     {'pool_name': 'Gold+OLTP+SRP_1+000197800123',
                      'location_info': '000197800123#SRP_1#OLTP#Gold'}]
        self.assertEqual(ref_pools, new_pools)

    def test_update_volume_group_name(self):
        group = self.data.test_group_1
        ref_group_name = self.data.test_vol_grp_name
        vol_grp_name = self.utils.update_volume_group_name(group)
        self.assertEqual(ref_group_name, vol_grp_name)

    def test_update_volume_group_name_id_only(self):
        group = self.data.test_group_without_name
        ref_group_name = self.data.test_vol_grp_name_id_only
        vol_grp_name = self.utils.update_volume_group_name(group)
        self.assertEqual(ref_group_name, vol_grp_name)

    def test_get_volume_group_utils(self):
        array, intervals_retries = self.utils.get_volume_group_utils(
            self.data.test_group_1, interval=1, retries=1)
        ref_array = self.data.array
        self.assertEqual(ref_array, array)

    def test_update_volume_model_updates(self):
        volume_model_updates = [{'id': '1', 'status': 'available'}]
        volumes = [self.data.test_volume]
        ref_val = {'id': self.data.test_volume.id,
                   'status': 'error_deleting'}
        ret_val = self.utils.update_volume_model_updates(
            volume_model_updates, volumes, 'abc', status='error_deleting')
        self.assertEqual(ref_val, ret_val[1])

    def test_update_volume_model_updates_empty_update_list(self):
        volume_model_updates = []
        volumes = [self.data.test_volume]
        ref_val = [{'id': self.data.test_volume.id,
                    'status': 'available'}]
        ret_val = self.utils.update_volume_model_updates(
            volume_model_updates, volumes, 'abc')
        self.assertEqual(ref_val, ret_val)

    def test_update_volume_model_updates_empty_vol_list(self):
        volume_model_updates, volumes, ref_val = [], [], []
        ret_val = self.utils.update_volume_model_updates(
            volume_model_updates, volumes, 'abc')
        self.assertEqual(ref_val, ret_val)

    def test_check_replication_matched(self):
        # Check 1: Volume is not part of a group
        self.utils.check_replication_matched(
            self.data.test_volume, self.data.extra_specs)
        group_volume = deepcopy(self.data.test_volume)
        group_volume.group = self.data.test_group
        with mock.patch.object(volume_utils, 'is_group_a_type',
                               return_value=False):
            # Check 2: Both volume and group have the same rep status
            self.utils.check_replication_matched(
                group_volume, self.data.extra_specs)
            # Check 3: Volume and group have different rep status
            with mock.patch.object(self.utils, 'is_replication_enabled',
                                   return_value=True):
                self.assertRaises(exception.InvalidInput,
                                  self.utils.check_replication_matched,
                                  group_volume, self.data.extra_specs)

    def test_check_rep_status_enabled(self):
        # Check 1: not replication enabled
        with mock.patch.object(volume_utils, 'is_group_a_type',
                               return_value=False):
            self.utils.check_rep_status_enabled(self.data.test_group)
        # Check 2: replication enabled, status enabled
        with mock.patch.object(volume_utils, 'is_group_a_type',
                               return_value=True):
            self.utils.check_rep_status_enabled(self.data.test_rep_group)
            # Check 3: replication enabled, status disabled
            self.assertRaises(exception.InvalidInput,
                              self.utils.check_rep_status_enabled,
                              self.data.test_group)

    def test_get_replication_prefix(self):
        async_prefix = self.utils.get_replication_prefix(utils.REP_ASYNC)
        self.assertEqual('-RA', async_prefix)
        sync_prefix = self.utils.get_replication_prefix(utils.REP_SYNC)
        self.assertEqual('-RE', sync_prefix)
        metro_prefix = self.utils.get_replication_prefix(utils.REP_METRO)
        self.assertEqual('-RM', metro_prefix)

    def test_get_rdf_management_group_name(self):
        rep_config = {'rdf_group_label': self.data.rdf_group_name_1,
                      'mode': utils.REP_ASYNC}
        grp_name = self.utils.get_rdf_management_group_name(rep_config)
        self.assertEqual(self.data.rdf_managed_async_grp, grp_name)

    def test_is_metro_device(self):
        rep_config = {'mode': utils.REP_METRO}
        is_metro = self.utils.is_metro_device(
            rep_config, self.data.rep_extra_specs)
        self.assertTrue(is_metro)
        rep_config2 = {'mode': utils.REP_ASYNC}
        is_metro2 = self.utils.is_metro_device(
            rep_config2, self.data.rep_extra_specs)
        self.assertFalse(is_metro2)

    def test_does_vol_need_rdf_management_group(self):
        extra_specs = deepcopy(self.data.rep_extra_specs)
        extra_specs['rep_mode'] = utils.REP_SYNC
        self.assertFalse(self.utils.does_vol_need_rdf_management_group(
            extra_specs))
        extra_specs[utils.REP_MODE] = utils.REP_ASYNC
        self.assertTrue(self.utils.does_vol_need_rdf_management_group(
            extra_specs))

    def test_modify_snapshot_prefix_manage(self):
        snap_name = self.data.snapshot_id
        expected_snap_name = self.data.managed_snap_id
        updated_name = self.utils.modify_snapshot_prefix(
            snap_name, manage=True)
        self.assertEqual(expected_snap_name, updated_name)

    def test_modify_snapshot_prefix_unmanage(self):
        snap_name = self.data.managed_snap_id
        expected_snap_name = self.data.snapshot_id
        updated_name = self.utils.modify_snapshot_prefix(
            snap_name, unmanage=True)
        self.assertEqual(expected_snap_name, updated_name)

    def test_change_replication(self):
        non_rep_extra_specs = self.data.extra_specs
        rep_extra_specs = self.data.extra_specs_rep_enabled
        change_rep = self.utils.change_replication(
            non_rep_extra_specs, rep_extra_specs)
        self.assertTrue(change_rep)

    def test_change_replication_different_backend_id(self):
        rep_extra_specs_a = deepcopy(self.data.extra_specs_rep_enabled)
        rep_extra_specs_a[utils.REPLICATION_DEVICE_BACKEND_ID] = 'A'
        rep_extra_specs_b = deepcopy(self.data.extra_specs_rep_enabled)
        rep_extra_specs_b[utils.REPLICATION_DEVICE_BACKEND_ID] = 'B'
        change_rep = self.utils.change_replication(
            rep_extra_specs_a, rep_extra_specs_b)
        self.assertTrue(change_rep)

    def test_change_replication_no_change(self):
        non_rep_extra_specs_a = self.data.extra_specs
        non_rep_extra_specs_b = self.data.extra_specs
        change_rep = self.utils.change_replication(
            non_rep_extra_specs_a, non_rep_extra_specs_b)
        self.assertFalse(change_rep)

    def test_change_replication_no_change_same_backend_id(self):
        rep_extra_specs_a = deepcopy(self.data.extra_specs_rep_enabled)
        rep_extra_specs_a[utils.REPLICATION_DEVICE_BACKEND_ID] = 'A'
        rep_extra_specs_b = deepcopy(self.data.extra_specs_rep_enabled)
        rep_extra_specs_b[utils.REPLICATION_DEVICE_BACKEND_ID] = 'A'
        change_rep = self.utils.change_replication(
            rep_extra_specs_a, rep_extra_specs_b)
        self.assertFalse(change_rep)

    def test_get_child_sg_name(self):
        host_name = 'HostX'
        port_group_label = self.data.port_group_name_f
        # Slo and rep enabled
        extra_specs1 = {
            'pool_name': u'Diamond+DSS+SRP_1+000197800123',
            'slo': 'Diamond',
            'workload': 'DSS',
            'srp': 'SRP_1',
            'array': self.data.array,
            'interval': 3,
            'retries': 120,
            'replication_enabled': True,
            'rep_mode': 'Synchronous',
            utils.PORTGROUPNAME: self.data.port_group_name_f}

        child_sg_name, do_disable_compression, rep_enabled = (
            self.utils.get_child_sg_name(
                host_name, extra_specs1, port_group_label))
        re_name = self.data.storagegroup_name_f + '-RE'
        self.assertEqual(re_name, child_sg_name)
        # Disable compression
        extra_specs2 = deepcopy(self.data.extra_specs_disable_compression)
        child_sg_name, do_disable_compression, rep_enabled = (
            self.utils.get_child_sg_name(
                host_name, extra_specs2, port_group_label))
        cd_name = self.data.storagegroup_name_f + '-CD'
        self.assertEqual(cd_name, child_sg_name)
        # No slo
        extra_specs3 = deepcopy(self.data.extra_specs)
        extra_specs3[utils.SLO] = None
        child_sg_name, do_disable_compression, rep_enabled = (
            self.utils.get_child_sg_name(
                host_name, extra_specs3, port_group_label))
        self.assertEqual(self.data.no_slo_sg_name, child_sg_name)

    def test_change_multiattach(self):
        extra_specs_ma_true = {'multiattach': '<is> True'}
        extra_specs_ma_false = {'multiattach': '<is> False'}
        self.assertTrue(self.utils.change_multiattach(
            extra_specs_ma_true, extra_specs_ma_false))
        self.assertFalse(self.utils.change_multiattach(
            extra_specs_ma_true, extra_specs_ma_true))
        self.assertFalse(self.utils.change_multiattach(
            extra_specs_ma_false, extra_specs_ma_false))

    def test_is_volume_manageable(self):
        for volume in self.data.priv_vol_func_response_multi:
            self.assertTrue(
                self.utils.is_volume_manageable(volume))
        for volume in self.data.priv_vol_func_response_multi_invalid:
            self.assertFalse(
                self.utils.is_volume_manageable(volume))

    def test_is_snapshot_manageable(self):
        for volume in self.data.priv_vol_func_response_multi:
            self.assertTrue(
                self.utils.is_snapshot_manageable(volume))
        for volume in self.data.priv_vol_func_response_multi_invalid:
            self.assertFalse(
                self.utils.is_snapshot_manageable(volume))

    def test_get_volume_attached_hostname(self):

        attached_volume = deepcopy(self.data.test_volume)
        attached_volume.volume_attachment.objects = [
            self.data.test_volume_attachment]
        # Success
        hostname = self.utils.get_volume_attached_hostname(attached_volume)
        self.assertEqual('HostX', hostname)

    def test_validate_qos_input_exception(self):
        qos_extra_spec = {'total_iops_sec': 90, 'DistributionType': 'Wrong',
                          'total_bytes_sec': 100}
        input_key = 'total_iops_sec'
        sg_value = 4000
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.utils.validate_qos_input, input_key, sg_value,
                          qos_extra_spec, {})
        input_key = 'total_bytes_sec'
        sg_value = 4000
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.utils.validate_qos_input, input_key, sg_value,
                          qos_extra_spec, {})

    def test_validate_qos_distribution_type(self):
        qos_extra_spec = {'total_iops_sec': 4000, 'DistributionType': 'Always',
                          'total_bytes_sec': 4194304000}
        input_prop_dict = {'total_iops_sec': 4000}
        sg_value = 'Always'
        ret_prop_dict = self.utils.validate_qos_distribution_type(
            sg_value, qos_extra_spec, input_prop_dict)
        self.assertEqual(input_prop_dict, ret_prop_dict)

    def test_validate_qos_cast_to_int(self):
        qos_extra_spec = {'total_iops_sec': '500',
                          'total_bytes_sec': '104857600',
                          'DistributionType': 'Always'}
        property_dict = {'host_io_limit_io_sec': 500}
        input_prop_dict = {'host_io_limit_io_sec': 500,
                           'host_io_limit_mb_sec': 100}
        input_key = 'total_bytes_sec'
        ret_prop_dict = self.utils.validate_qos_input(
            input_key, None, qos_extra_spec, property_dict)
        self.assertEqual(input_prop_dict, ret_prop_dict)

    def test_validate_qos_cast_to_int_drop_fraction(self):
        qos_extra_spec = {'total_iops_sec': '500',
                          'total_bytes_sec': '105000000',
                          'DistributionType': 'Always'}
        property_dict = {'host_io_limit_io_sec': 500}
        input_prop_dict = {'host_io_limit_io_sec': 500,
                           'host_io_limit_mb_sec': 100}
        input_key = 'total_bytes_sec'
        ret_prop_dict = self.utils.validate_qos_input(
            input_key, None, qos_extra_spec, property_dict)
        self.assertEqual(input_prop_dict, ret_prop_dict)

    def test_compare_cylinders(self):
        source_cylinders = '12345'
        target_cylinders = '12345'
        self.utils.compare_cylinders(source_cylinders, target_cylinders)

    def test_compare_cylinders_target_larger(self):
        source_cylinders = '12345'
        target_cylinders = '12346'
        self.utils.compare_cylinders(source_cylinders, target_cylinders)

    def test_compare_cylinders_source_larger(self):
        source_cylinders = '12347'
        target_cylinders = '12346'
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.utils.compare_cylinders, source_cylinders,
                          target_cylinders)

    def test_get_grp_volume_model_update(self):
        volume = self.data.test_volume
        volume_dict = self.data.provider_location
        group_id = self.data.gvg_group_id
        metadata = self.data.volume_metadata

        ref_model_update_meta = {
            'id': volume.id, 'status': 'available', 'metadata': metadata,
            'provider_location': six.text_type(volume_dict)}
        act_model_update_meta = self.utils.get_grp_volume_model_update(
            volume, volume_dict, group_id, metadata)
        self.assertEqual(ref_model_update_meta, act_model_update_meta)

        ref_model_update_no_meta = {
            'id': volume.id, 'status': 'available',
            'provider_location': six.text_type(volume_dict)}
        act_model_update_no_meta = self.utils.get_grp_volume_model_update(
            volume, volume_dict, group_id)
        self.assertEqual(ref_model_update_no_meta, act_model_update_no_meta)

    def test_get_service_level_workload(self):
        # Service Level set to None
        extra_specs = deepcopy(self.data.extra_specs)
        extra_specs[utils.SLO] = None
        sl_1, wl_1 = self.utils.get_service_level_workload(extra_specs)
        self.assertEqual('None', sl_1)
        self.assertEqual('None', wl_1)
        # Service Level set to None and Workload set
        extra_specs[utils.WORKLOAD] = 'DSS'
        sl_2, wl_2 = self.utils.get_service_level_workload(extra_specs)
        self.assertEqual('None', sl_2)
        self.assertEqual('None', wl_2)
        # Service Level and Workload both set
        extra_specs[utils.SLO] = 'Diamond'
        extra_specs[utils.WORKLOAD] = 'DSS'
        sl_3, wl_3 = self.utils.get_service_level_workload(extra_specs)
        self.assertEqual('Diamond', sl_3)
        self.assertEqual('DSS', wl_3)

    def test_get_new_tags_none(self):
        list_str1 = 'finance, production,   test'
        list_str2 = 'production,test,finance'

        self.assertEqual(
            [], self.utils.get_new_tags(list_str1, list_str2))

    def test_get_new_tags_one(self):
        list_str1 = 'finance, production,   test'
        list_str2 = 'production,test'

        self.assertEqual(
            ['finance'], self.utils.get_new_tags(list_str1, list_str2))

    def test_get_new_tags_two(self):
        list_str1 = 'finance, production,   test, test2'
        list_str2 = 'production,test'

        self.assertEqual(
            ['finance', 'test2'], self.utils.get_new_tags(
                list_str1, list_str2))

    def test_get_new_tags_case(self):
        list_str1 = 'Finance, Production,   test, tEst2'
        list_str2 = 'production,test'

        self.assertEqual(
            ['Finance', 'tEst2'], self.utils.get_new_tags(
                list_str1, list_str2))

    def test_get_new_tags_empty_string_first(self):
        list_str1 = ''
        list_str2 = 'production,test'

        self.assertEqual(
            [], self.utils.get_new_tags(
                list_str1, list_str2))

    def test_get_new_tags_empty_string_second(self):
        list_str1 = 'production,test'
        list_str2 = '  '

        self.assertEqual(
            ['production', 'test'], self.utils.get_new_tags(
                list_str1, list_str2))

    def test_get_intersection(self):
        list_str1 = 'finance,production'
        list_str2 = 'production'

        common_list = self.utils._get_intersection(
            list_str1, list_str2)

        self.assertEqual(['production'], common_list)

    def test_get_intersection_unordered_list(self):
        list_str1 = 'finance,production'
        list_str2 = 'production, finance'

        common_list = (
            self.utils._get_intersection(list_str1, list_str2))

        self.assertEqual(['finance', 'production'], common_list)

    def test_verify_tag_list_good(self):
        tag_list = ['no', 'InValid', 'characters', 'dash-allowed',
                    '123', 'underscore_allowed',
                    ' leading_space', 'trailing-space ']
        self.assertTrue(self.utils.verify_tag_list(tag_list))

    def test_verify_tag_list_space(self):
        tag_list = ['bad space']
        self.assertFalse(self.utils.verify_tag_list(tag_list))

    def test_verify_tag_list_forward_slash(self):
        tag_list = ['\\forward\\slash']
        self.assertFalse(self.utils.verify_tag_list(tag_list))

    def test_verify_tag_list_square_bracket(self):
        tag_list = ['[squareBrackets]']
        self.assertFalse(self.utils.verify_tag_list(tag_list))

    def test_verify_tag_list_backward_slash(self):
        tag_list = ['/backward/slash']
        self.assertFalse(self.utils.verify_tag_list(tag_list))

    def test_verify_tag_list_curly_bracket(self):
        tag_list = ['{curlyBrackets}']
        self.assertFalse(self.utils.verify_tag_list(tag_list))

    def test_verify_tag_list_empty_list(self):
        tag_list = []
        self.assertFalse(self.utils.verify_tag_list(tag_list))

    def test_verify_tag_list_not_a_list(self):
        tag_list = '1,2,3,4'
        self.assertFalse(self.utils.verify_tag_list(tag_list))

    def test_verify_tag_list_exceeds_8(self):
        tag_list = ['1', '2', '3', '4', '5', '6', '7', '8', '9']
        self.assertFalse(self.utils.verify_tag_list(tag_list))

    def test_convert_list_to_string(self):
        input_list = ['one', 'two', 'three']
        output_string = self.utils.convert_list_to_string(input_list)
        self.assertEqual('one,two,three', output_string)

    def test_convert_list_to_string_input_string(self):
        input_list = 'one,two,three'
        output_string = self.utils.convert_list_to_string(input_list)
        self.assertEqual('one,two,three', output_string)

    def test_regex_check_case_2(self):
        test_template = 'shortHostName[:10]uuid[:5]'
        is_ok, case = self.utils.regex_check(test_template, True)
        self.assertTrue(is_ok)
        self.assertEqual('2', case)

    def test_regex_check_case_3(self):
        test_template = 'shortHostName[-10:]uuid[:5]'
        is_ok, case = self.utils.regex_check(test_template, True)
        self.assertTrue(is_ok)
        self.assertEqual('3', case)

    def test_regex_check_case_4(self):
        test_template = 'shortHostName[:7]finance'
        is_ok, case = self.utils.regex_check(test_template, True)
        self.assertTrue(is_ok)
        self.assertEqual('4', case)

    def test_regex_check_case_5(self):
        test_template = 'shortHostName[-6:]production'
        is_ok, case = self.utils.regex_check(test_template, True)
        self.assertTrue(is_ok)
        self.assertEqual('5', case)

    def test_regex_check_case_2_misspelt(self):
        test_template = 'shortHstName[:10]uuid[:5]'
        is_ok, case = self.utils.regex_check(test_template, True)
        self.assertFalse(is_ok)
        self.assertEqual('0', case)

    def test_regex_check_case_3_misspelt(self):
        test_template = 'shortHostName[-10:]uud[:5]'
        is_ok, case = self.utils.regex_check(test_template, True)
        self.assertFalse(is_ok)
        self.assertEqual('0', case)

    def test_regex_check_case_4_misspelt(self):
        test_template = 'shortHotName[:7]finance'
        is_ok, case = self.utils.regex_check(test_template, True)
        self.assertFalse(is_ok)
        self.assertEqual('0', case)

    def test_regex_check_case_5_misspelt(self):
        test_template = 'shortHstName[-6:]production'
        is_ok, case = self.utils.regex_check(test_template, True)
        self.assertFalse(is_ok)
        self.assertEqual('0', case)

    def test_regex_check_case_4_invalid_chars(self):
        test_template = 'shortHostName[:7]f*n&nce'
        is_ok, case = self.utils.regex_check(test_template, True)
        self.assertFalse(is_ok)
        self.assertEqual('0', case)

    def test_regex_check_case_5_invalid_chars(self):
        test_template = 'shortHostName[-6:]pr*ducti*n'
        is_ok, case = self.utils.regex_check(test_template, True)
        self.assertFalse(is_ok)
        self.assertEqual('0', case)

    def test_regex_check_case_2_missing_square_bracket(self):
        test_template = 'shortHostName[:10uuid[:5]'
        is_ok, case = self.utils.regex_check(test_template, True)
        self.assertFalse(is_ok)
        self.assertEqual('0', case)

    def test_regex_check_case_4_missing_square_bracket(self):
        test_template = 'shortHostName[:10finance'
        is_ok, case = self.utils.regex_check(test_template, True)
        self.assertFalse(is_ok)
        self.assertEqual('0', case)

    def test_prepare_string_entity_case_2(self):
        test_template = 'shortHostName[:10]uuid[:5]'
        altered_string = self.utils.prepare_string_entity(
            test_template, 'my_short_host_name', True)
        self.assertEqual(
            'my_short_host_name[:10]uuid[:5]',
            altered_string)

    def test_prepare_string_entity_case_3(self):
        test_template = 'shortHostName[-10:]uuid[:5]'
        altered_string = self.utils.prepare_string_entity(
            test_template, 'my_short_host_name', True)
        self.assertEqual(
            'my_short_host_name[-10:]uuid[:5]',
            altered_string)

    def test_prepare_string_entity_case_4(self):
        test_template = 'shortHostName[:7]finance'
        altered_string = self.utils.prepare_string_entity(
            test_template, 'my_short_host_name', True)
        self.assertEqual(
            'my_short_host_name[:7]finance',
            altered_string)

    def test_prepare_string_entity_case_5(self):
        test_template = 'shortHostName[-6:]production'
        altered_string = self.utils.prepare_string_entity(
            test_template, 'my_short_host_name', True)
        self.assertEqual(
            'my_short_host_name[-6:]production',
            altered_string)

    def test_prepare_string_with_uuid_case_2(self):
        test_template = 'shortHostName[:10]uuid[:5]'
        pass_two, uuid = self.utils.prepare_string_with_uuid(
            test_template, 'my_short_host_name', True)
        self.assertEqual(
            'my_short_host_name[:10]944854dce45898b544a1cb9071d3cc35[:5]',
            pass_two)
        self.assertEqual('944854dce45898b544a1cb9071d3cc35', uuid)

    def test_prepare_string_with_uuid_case_3(self):
        test_template = 'shortHostName[-10:]uuid[:5]'
        pass_two, uuid = self.utils.prepare_string_with_uuid(
            test_template, 'my_short_host_name', True)
        self.assertEqual(
            'my_short_host_name[-10:]944854dce45898b544a1cb9071d3cc35[:5]',
            pass_two)
        self.assertEqual('944854dce45898b544a1cb9071d3cc35', uuid)

    def test_check_upper_limit_short_host(self):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.utils.check_upper_limit,
                          12, 12, True)

    def test_check_upper_limit_short_host_case_4(self):
        user_define_name = 'Little_too_long'
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.utils.check_upper_limit,
                          12, len(user_define_name), True)

    def test_validate_short_host_name_from_template_case_1(self):
        test_template = 'shortHostName'
        short_host_name = 'my_short_host'
        result_string = self.utils.validate_short_host_name_from_template(
            test_template, short_host_name)
        self.assertEqual('my_short_host', result_string)

    def test_validate_short_host_name_from_template_case_1_exceeds_16char(
            self):
        test_template = 'shortHostName'
        short_host_name = 'my_short_host_greater_than_16chars'
        result_string = self.utils.validate_short_host_name_from_template(
            test_template, short_host_name)
        self.assertEqual('6chars0bc43f914e', result_string)

    def test_validate_short_host_name_from_template_case_1_template_misspelt(
            self):
        test_template = 'shortHstName'
        short_host_name = 'my_short_host'
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.utils.validate_short_host_name_from_template,
                          test_template, short_host_name)

    def test_validate_short_host_name_from_template_case_2(self):
        test_template = 'shortHostName[:10]uuid[:5]'
        short_host_name = 'my_short_host_name'
        result_string = self.utils.validate_short_host_name_from_template(
            test_template, short_host_name)
        self.assertEqual('my_short_h94485', result_string)

    def test_validate_short_host_name_from_template_case_2_shorter_than(self):
        test_template = 'shortHostName[:10]uuid[:5]'
        short_host_name = 'HostX'
        result_string = self.utils.validate_short_host_name_from_template(
            test_template, short_host_name)
        self.assertEqual('HostX699ea', result_string)

    def test_validate_short_host_name_from_template_case_3(self):
        test_template = 'shortHostName[-10:]uuid[:5]'
        short_host_name = 'my_short_host_name'
        result_string = self.utils.validate_short_host_name_from_template(
            test_template, short_host_name)
        self.assertEqual('_host_name94485', result_string)

    def test_validate_short_host_name_from_template_case_3_shorter_than(self):
        test_template = 'shortHostName[-10:]uuid[:5]'
        short_host_name = 'HostX'
        result_string = self.utils.validate_short_host_name_from_template(
            test_template, short_host_name)
        self.assertEqual('HostX699ea', result_string)

    def test_validate_short_host_name_from_template_case_4(self):
        test_template = 'shortHostName[:7]finance'
        short_host_name = 'my_short_host_name'
        result_string = self.utils.validate_short_host_name_from_template(
            test_template, short_host_name)
        self.assertEqual('my_shorfinance', result_string)

    def test_validate_short_host_name_from_template_case_5(self):
        test_template = 'shortHostName[-6:]production'
        short_host_name = 'my_short_host_name'
        result_string = self.utils.validate_short_host_name_from_template(
            test_template, short_host_name)
        self.assertEqual('t_nameproduction', result_string)

    def test_validate_short_host_name_exception_missing_minus(self):
        test_template = 'shortHostName[6:]production'
        short_host_name = 'my_short_host_name'
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.utils.validate_short_host_name_from_template,
                          test_template, short_host_name)

    def test_validate_port_group_from_template_case_1(self):
        test_template = 'portGroupName'
        port_group_name = 'my_pg'
        result_string = self.utils.validate_port_group_name_from_template(
            test_template, port_group_name)
        self.assertEqual('my_pg', result_string)

    def test_validate_port_group_from_template_case_1_long(self):
        test_template = 'portGroupName'
        port_group_name = 'my_port_group_name'
        result_string = self.utils.validate_port_group_name_from_template(
            test_template, port_group_name)
        self.assertEqual('p_name5ba163', result_string)

    def test_validate_port_group_from_template_case_1_misspelt(self):
        test_template = 'portGr*upName'
        port_group_name = 'my_port_group_name'
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.utils.validate_port_group_name_from_template,
                          test_template, port_group_name)

    def test_validate_port_group_from_template_case_2(self):
        test_template = 'portGroupName[:6]uuid[:5]'
        port_group_name = 'my_port_group_name'
        result_string = self.utils.validate_port_group_name_from_template(
            test_template, port_group_name)
        self.assertEqual('my_por3b02c', result_string)

    def test_validate_port_group_from_template_case_3(self):
        test_template = 'portGroupName[-6:]uuid[:5]'
        port_group_name = 'my_port_group_name'
        result_string = self.utils.validate_port_group_name_from_template(
            test_template, port_group_name)
        self.assertEqual('p_name3b02c', result_string)

    def test_validate_port_group_from_template_case_4(self):
        test_template = 'portGroupName[:6]test'
        port_group_name = 'my_port_group_name'
        result_string = self.utils.validate_port_group_name_from_template(
            test_template, port_group_name)
        self.assertEqual('my_portest', result_string)

    def test_validate_port_group_from_template_case_5(self):
        test_template = 'portGroupName[-7:]test'
        port_group_name = 'my_port_group_name'
        result_string = self.utils.validate_port_group_name_from_template(
            test_template, port_group_name)
        self.assertEqual('up_nametest', result_string)

    def test_validate_port_group_name_exception_missing_minus(self):
        test_template = 'portGroupName[6:]test'
        port_group_name = 'my_port_group_name'
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.utils.validate_port_group_name_from_template,
                          test_template, port_group_name)

    def test_validate_port_group_name_exception_chars_exceeded(self):
        test_template = 'portGroupName[:10]test'
        port_group_name = 'my_port_group_name'
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.utils.validate_port_group_name_from_template,
                          test_template, port_group_name)

    def test_get_port_name_label_default(self):
        port_name_in = 'my_port_group_name'
        port_group_template = 'portGroupName'
        port_name_out = self.utils.get_port_name_label(
            port_name_in, port_group_template)
        self.assertEqual('p_name5ba163', port_name_out)

    def test_get_port_name_label_template(self):
        port_name_in = 'my_port_group_name'
        port_group_template = 'portGroupName[-6:]uuid[:5]'
        port_name_out = self.utils.get_port_name_label(
            port_name_in, port_group_template)
        self.assertEqual('p_name3b02c', port_name_out)

    def test_get_rdf_managed_storage_group(self):
        rdf_component_dict = ('OS-23_24_007-Asynchronous-rdf-sg',
                              {'prefix': 'OS',
                               'rdf_label': '23_24_007',
                               'sync_mode': 'Asynchronous',
                               'after_mode': 'rdf-sg'})

        async_rdf_details = (
            self.utils.get_rdf_managed_storage_group(
                self.data.volume_details_attached_async))
        self.assertEqual(rdf_component_dict, async_rdf_details)

    def test_get_storage_group_component_dict_no_slo(self):
        """Test for get_storage_group_component_dict.

        REST and no SLO.
        """
        sg_no_slo = 'OS-myhost-No_SLO-os-iscsi-pg'
        component_dict = self.utils.get_storage_group_component_dict(
            sg_no_slo)
        self.assertEqual('myhost', component_dict['host'])
        self.assertEqual('OS', component_dict['prefix'])
        self.assertEqual('No_SLO', component_dict['no_slo'])
        self.assertEqual('os-iscsi-pg', component_dict['portgroup'])
        self.assertIsNone(component_dict['sloworkload'])
        self.assertIsNone(component_dict['srp'])

    def test_get_storage_group_component_dict_slo_workload_2(self):
        """Test for get_storage_group_component_dict.

        SLO, workload and test 2.
        """
        sg_slo_workload = 'OS-myhost-SRP_1-DiamodOLTP-os-iscsi-pg-RE'
        component_dict = self.utils.get_storage_group_component_dict(
            sg_slo_workload)
        self.assertEqual('OS', component_dict['prefix'])
        self.assertEqual('myhost', component_dict['host'])
        self.assertEqual('SRP_1', component_dict['srp'])
        self.assertEqual('os-iscsi-pg', component_dict['portgroup'])
        self.assertEqual('DiamodOLTP', component_dict['sloworkload'])
        self.assertIsNone(component_dict['no_slo'])

    def test_get_storage_group_component_dict_compression_disabled(self):
        """Test for get_storage_group_component_dict.

        Compression disabled.
        """
        sg_compression_disabled = 'OS-myhost-SRP_1-DiamodNONE-os-iscsi-pg-CD'
        component_dict = self.utils.get_storage_group_component_dict(
            sg_compression_disabled)
        self.assertEqual('OS', component_dict['prefix'])
        self.assertEqual('myhost', component_dict['host'])
        self.assertEqual('SRP_1', component_dict['srp'])
        self.assertEqual('os-iscsi-pg', component_dict['portgroup'])
        self.assertEqual('DiamodNONE', component_dict['sloworkload'])
        self.assertEqual('-CD', component_dict['after_pg'])
        self.assertIsNone(component_dict['no_slo'])

    def test_get_storage_group_component_dict_replication_enabled(self):
        """Test for get_storage_group_component_dict.

        Replication enabled.
        """
        sg_slo_workload_rep = 'OS-myhost-SRP_1-DiamodOLTP-os-iscsi-pg-RE'
        component_dict = self.utils.get_storage_group_component_dict(
            sg_slo_workload_rep)
        self.assertEqual('OS', component_dict['prefix'])
        self.assertEqual('myhost', component_dict['host'])
        self.assertEqual('SRP_1', component_dict['srp'])
        self.assertEqual('os-iscsi-pg', component_dict['portgroup'])
        self.assertEqual('DiamodOLTP', component_dict['sloworkload'])
        self.assertEqual('-RE', component_dict['after_pg'])
        self.assertIsNone(component_dict['no_slo'])

    def test_get_storage_group_component_dict_slo_no_workload(self):
        """Test for get_storage_group_component_dict.

        SLO and no workload.
        """
        sg_slo_no_workload = 'OS-myhost-SRP_1-DiamodNONE-os-iscsi-pg'
        component_dict = self.utils.get_storage_group_component_dict(
            sg_slo_no_workload)
        self.assertEqual('OS', component_dict['prefix'])
        self.assertEqual('myhost', component_dict['host'])
        self.assertEqual('SRP_1', component_dict['srp'])
        self.assertEqual('os-iscsi-pg', component_dict['portgroup'])
        self.assertEqual('DiamodNONE', component_dict['sloworkload'])
        self.assertIsNone(component_dict['no_slo'])

    def test_get_storage_group_component_dict_dashes(self):
        """Test for get_storage_group_component_dict, dashes."""
        sg_host_with_dashes = (
            'OS-host-with-dashes-SRP_1-DiamodOLTP-myportgroup-RE')
        component_dict = self.utils.get_storage_group_component_dict(
            sg_host_with_dashes)
        self.assertEqual('host-with-dashes', component_dict['host'])
        self.assertEqual('OS', component_dict['prefix'])
        self.assertEqual('SRP_1', component_dict['srp'])
        self.assertEqual('DiamodOLTP', component_dict['sloworkload'])
        self.assertEqual('myportgroup', component_dict['portgroup'])
        self.assertEqual('-RE', component_dict['after_pg'])

    def test_delete_values_from_dict(self):
        """Test delete_values_from_dict"""
        delete_list = ['rdf_group_no', 'rep_mode', 'target_array_model',
                       'service_level', 'remote_array', 'target_device_id',
                       'replication_status', 'rdf_group_label']
        data_dict = self.utils.delete_values_from_dict(
            self.data.retype_metadata_dict, delete_list)
        self.assertEqual({'device_id': self.data.device_id}, data_dict)

    def test_update_values_in_dict(self):
        """Test delete_values_from_dict"""
        update_list = [('default_sg_name', 'source_sg_name'),
                       ('service_level', 'source_service_level')]

        update_dict = {'default_sg_name': 'default-sg',
                       'service_level': 'Diamond'}
        ret_dict = {'source_sg_name': 'default-sg',
                    'source_service_level': 'Diamond'}
        data_dict = self.utils.update_values_in_dict(
            update_dict, update_list)
        self.assertEqual(ret_dict, data_dict)

    def test_get_unique_device_ids_from_lists(self):
        list_a = ['00001', '00002', '00003']
        list_b = ['00002', '00003', '00004']
        unique_ids = self.utils.get_unique_device_ids_from_lists(
            list_a, list_b)
        self.assertEqual(['00004'], unique_ids)

    def test_update_payload_for_rdf_vol_create(self):
        payload = {
            'array': self.data.array,
            'editStorageGroupActionParam': {
                'expandStorageGroupParam': {
                    'addVolumeParam': {'create_new_volumes': 'False'}}}}

        updated_payload = self.utils.update_payload_for_rdf_vol_create(
            payload, self.data.remote_array, self.data.storagegroup_name_f)
        expected_payload = {
            'array': self.data.array,
            'editStorageGroupActionParam': {
                'expandStorageGroupParam': {
                    'addVolumeParam': {
                        'create_new_volumes': 'True',
                        'remoteSymmSGInfoParam': {
                            'force': 'true',
                            'remote_symmetrix_1_id': self.data.remote_array,
                            'remote_symmetrix_1_sgs': [
                                self.data.storagegroup_name_f]}}}}}
        self.assertEqual(expected_payload, updated_payload)

    def test_is_retype_supported(self):
        # Volume source type not replicated, target type Metro replicated,
        # volume is detached, host-assisted retype supported
        volume = self.data.test_volume
        volume.attach_status = 'detached'

        src_extra_specs = deepcopy(self.data.extra_specs)
        src_extra_specs['rep_mode'] = None

        tgt_extra_specs = deepcopy(self.data.rep_extra_specs)
        tgt_extra_specs['rep_mode'] = utils.REP_METRO

        rep_configs = self.data.multi_rep_config_list
        src_extra_specs[utils.REPLICATION_DEVICE_BACKEND_ID] = (
            self.data.rep_backend_id_sync)
        tgt_extra_specs[utils.REPLICATION_DEVICE_BACKEND_ID] = (
            self.data.rep_backend_id_metro)

        self.assertTrue(self.utils.is_retype_supported(
            volume, src_extra_specs, tgt_extra_specs, rep_configs))

        # Volume source type not replicated, target type Metro replicated,
        # volume is attached, host-assisted retype not supported
        volume.attach_status = 'attached'
        self.assertFalse(self.utils.is_retype_supported(
            volume, src_extra_specs, tgt_extra_specs, rep_configs))

        # Volume source type Async replicated, target type Metro replicated,
        # volume is attached, host-assisted retype not supported
        src_extra_specs['rep_mode'] = utils.REP_ASYNC
        self.assertFalse(self.utils.is_retype_supported(
            volume, src_extra_specs, tgt_extra_specs, rep_configs))

        # Volume source type Metro replicated, target type Metro replicated,
        # volume is attached, host-assisted retype supported
        src_extra_specs['rep_mode'] = utils.REP_METRO
        self.assertTrue(self.utils.is_retype_supported(
            volume, src_extra_specs, tgt_extra_specs, rep_configs))

    def test_validate_multiple_rep_device(self):
        self.utils.validate_multiple_rep_device(self.data.multi_rep_device)

    def test_validate_multiple_rep_device_non_unique_backend_id(self):
        rep_devices = deepcopy(self.data.multi_rep_device)
        rep_devices[0][utils.BACKEND_ID] = rep_devices[1][utils.BACKEND_ID]
        self.assertRaises(
            exception.InvalidConfigurationValue,
            self.utils.validate_multiple_rep_device,
            rep_devices)

    def test_validate_multiple_rep_device_promotion_start_backend_id(self):
        backend_id = utils.PMAX_FAILOVER_START_ARRAY_PROMOTION
        rep_devices = deepcopy(self.data.multi_rep_device)
        rep_devices[0][utils.BACKEND_ID] = backend_id
        self.assertRaises(
            exception.InvalidConfigurationValue,
            self.utils.validate_multiple_rep_device,
            rep_devices)

    def test_validate_multiple_rep_device_missing_backend_id(self):
        rep_devices = deepcopy(self.data.multi_rep_device)
        rep_devices[0].pop(utils.BACKEND_ID)
        self.assertRaises(
            exception.InvalidConfigurationValue,
            self.utils.validate_multiple_rep_device,
            rep_devices)

    def test_validate_multiple_rep_device_non_unique_rdf_label(self):
        rep_devices = deepcopy(self.data.multi_rep_device)
        rep_devices[0]['rdf_group_label'] = rep_devices[1]['rdf_group_label']
        self.assertRaises(
            exception.InvalidConfigurationValue,
            self.utils.validate_multiple_rep_device,
            rep_devices)

    def test_validate_multiple_rep_device_non_unique_rdf_modes(self):
        rep_devices = [self.data.rep_dev_1, deepcopy(self.data.rep_dev_2)]
        rep_devices[1]['mode'] = rep_devices[0]['mode']
        self.assertRaises(
            exception.InvalidConfigurationValue,
            self.utils.validate_multiple_rep_device,
            rep_devices)

    def test_validate_multiple_rep_device_defaulting_rdf_modes(self):
        rep_devices = [
            deepcopy(self.data.rep_dev_1), deepcopy(self.data.rep_dev_2)]
        rep_devices[0]['mode'] = ''
        rep_devices[1]['mode'] = 'testing'
        self.assertRaises(
            exception.InvalidConfigurationValue,
            self.utils.validate_multiple_rep_device,
            rep_devices)

    def test_validate_multiple_rep_device_multiple_targets(self):
        rep_devices = [self.data.rep_dev_1, deepcopy(self.data.rep_dev_2)]
        rep_devices[1]['target_device_id'] = 1234
        self.assertRaises(
            exception.InvalidConfigurationValue,
            self.utils.validate_multiple_rep_device,
            rep_devices)

    def test_validate_multiple_rep_device_length(self):
        rep_devices = [1, 2, 3, 4]
        self.assertRaises(
            exception.InvalidConfigurationValue,
            self.utils.validate_multiple_rep_device,
            rep_devices)

    def test_get_rep_config_single_rep(self):
        rep_configs = self.data.sync_rep_config_list
        rep_config = self.utils.get_rep_config('test', rep_configs)
        self.assertEqual(rep_config, rep_configs[0])

    def test_get_rep_config_multi_rep(self):
        rep_configs = self.data.multi_rep_config_list
        backend_id = rep_configs[0][utils.BACKEND_ID]
        rep_device = self.utils.get_rep_config(backend_id, rep_configs)
        self.assertEqual(rep_configs[0], rep_device)

    def test_get_rep_config_fail_non_legacy_backend_id_message(self):
        rep_configs = self.data.multi_rep_config_list
        backend_id = 'invalid_backend_id'
        try:
            self.utils.get_rep_config(backend_id, rep_configs)
        except exception.InvalidInput as e:
            expected_str = 'Could not find replication_device. Legacy'
            excep_msg = str(e)
            self.assertNotIn(expected_str, excep_msg)

    def test_get_rep_config_fail_legacy_backend_id_message(self):
        rep_configs = self.data.multi_rep_config_list
        backend_id = utils.BACKEND_ID_LEGACY_REP
        try:
            self.utils.get_rep_config(backend_id, rep_configs)
        except exception.InvalidInput as e:
            expected_str = 'Could not find replication_device. Legacy'
            excep_msg = str(e)
            self.assertIn(expected_str, excep_msg)

    def test_get_rep_config_promotion_stats(self):
        rep_configs = self.data.multi_rep_config_list
        backend_id = 'testing'
        rep_device = self.utils.get_rep_config(backend_id, rep_configs, True)
        self.assertEqual(rep_configs[0], rep_device)

    def test_get_replication_targets(self):
        rep_targets_expected = [self.data.remote_array]
        rep_configs = self.data.multi_rep_config_list
        rep_targets_actual = self.utils.get_replication_targets(rep_configs)
        self.assertEqual(rep_targets_expected, rep_targets_actual)

    def test_validate_failover_request_success(self):
        is_failed_over = False
        is_promoted = False
        failover_backend_id = self.data.rep_backend_id_sync
        rep_configs = self.data.multi_rep_config_list
        primary_array = self.data.array
        array_list = [self.data.array]
        is_valid, msg = self.utils.validate_failover_request(
            is_failed_over, failover_backend_id, rep_configs,
            primary_array, array_list, is_promoted)
        self.assertTrue(is_valid)
        self.assertEqual("", msg)

    def test_validate_failover_request_already_failed_over(self):
        is_failed_over = True
        is_promoted = False
        failover_backend_id = self.data.rep_backend_id_sync
        rep_configs = self.data.multi_rep_config_list
        primary_array = self.data.array
        array_list = [self.data.array]
        is_valid, msg = self.utils.validate_failover_request(
            is_failed_over, failover_backend_id, rep_configs,
            primary_array, array_list, is_promoted)
        self.assertFalse(is_valid)
        expected_msg = ('Cannot failover, the backend is already in a failed '
                        'over state, if you meant to failback, please add '
                        '--backend_id default to the command.')
        self.assertEqual(expected_msg, msg)

    def test_validate_failover_request_failback_missing_array(self):
        is_failed_over = True
        is_promoted = False
        failover_backend_id = 'default'
        rep_configs = self.data.multi_rep_config_list
        primary_array = self.data.array
        array_list = [self.data.remote_array]
        is_valid, msg = self.utils.validate_failover_request(
            is_failed_over, failover_backend_id, rep_configs,
            primary_array, array_list, is_promoted)
        self.assertFalse(is_valid)
        expected_msg = ('Cannot failback, the configured primary array is '
                        'not currently available to perform failback to. '
                        'Please ensure array %s is visible in '
                        'Unisphere.') % primary_array
        self.assertEqual(expected_msg, msg)

    def test_validate_failover_request_promotion_finalize(self):
        is_failed_over = True
        is_promoted = True
        failover_backend_id = utils.PMAX_FAILOVER_START_ARRAY_PROMOTION
        rep_configs = self.data.multi_rep_config_list
        primary_array = self.data.array
        array_list = [self.data.array]
        is_valid, msg = self.utils.validate_failover_request(
            is_failed_over, failover_backend_id, rep_configs,
            primary_array, array_list, is_promoted)
        self.assertFalse(is_valid)
        expected_msg = ('Failover promotion currently in progress, please '
                        'finish the promotion process and issue a failover '
                        'using the "default" backend_id to complete this '
                        'process.')
        self.assertEqual(expected_msg, msg)

    def test_validate_failover_request_invalid_failback(self):
        is_failed_over = False
        is_promoted = False
        failover_backend_id = 'default'
        rep_configs = self.data.multi_rep_config_list
        primary_array = self.data.array
        array_list = [self.data.array]
        is_valid, msg = self.utils.validate_failover_request(
            is_failed_over, failover_backend_id, rep_configs,
            primary_array, array_list, is_promoted)
        self.assertFalse(is_valid)
        expected_msg = ('Cannot failback, backend is not in a failed over '
                        'state. If you meant to failover, please either omit '
                        'the --backend_id parameter or use the --backend_id '
                        'parameter with a valid backend id.')
        self.assertEqual(expected_msg, msg)

    def test_validate_replication_group_config_success(self):
        rep_configs = deepcopy(self.data.multi_rep_config_list)
        extra_specs = deepcopy(
            self.data.vol_type_extra_specs_rep_enabled_backend_id_sync)
        extra_specs[utils.REPLICATION_DEVICE_BACKEND_ID] = (
            self.data.rep_backend_id_sync)
        self.utils.validate_replication_group_config(
            rep_configs, [extra_specs])

    def test_validate_replication_group_config_no_rep_configured(self):
        rep_configs = None
        extra_specs_list = [
            self.data.vol_type_extra_specs_rep_enabled_backend_id_sync]
        self.assertRaises(exception.InvalidInput,
                          self.utils.validate_replication_group_config,
                          rep_configs, extra_specs_list)
        try:
            self.utils.validate_replication_group_config(
                rep_configs, extra_specs_list)
        except exception.InvalidInput as e:
            expected_msg = (
                'Invalid input received: No replication devices are defined '
                'in cinder.conf, can not enable volume group replication.')
            self.assertEqual(expected_msg, e.msg)

    def test_validate_replication_group_config_vol_type_not_rep_enabled(self):
        rep_configs = self.data.multi_rep_config_list
        extra_specs_list = [self.data.vol_type_extra_specs]
        self.assertRaises(exception.InvalidInput,
                          self.utils.validate_replication_group_config,
                          rep_configs, extra_specs_list)
        try:
            self.utils.validate_replication_group_config(
                rep_configs, extra_specs_list)
        except exception.InvalidInput as e:
            expected_msg = (
                'Invalid input received: Replication is not enabled for a '
                'Volume Type, all Volume Types in a replication enabled '
                'Volume Group must have replication enabled.')
            self.assertEqual(expected_msg, e.msg)

    def test_validate_replication_group_config_cant_get_rep_config(self):
        rep_configs = self.data.multi_rep_config_list
        vt_extra_specs = (
            self.data.vol_type_extra_specs_rep_enabled_backend_id_sync)
        vt_extra_specs[utils.REPLICATION_DEVICE_BACKEND_ID] = 'invalid'
        extra_specs_list = [vt_extra_specs]
        self.assertRaises(exception.InvalidInput,
                          self.utils.validate_replication_group_config,
                          rep_configs, extra_specs_list)
        try:
            self.utils.validate_replication_group_config(
                rep_configs, extra_specs_list)
        except exception.InvalidInput as e:
            expected_msg = (
                'Invalid input received: Unable to determine which '
                'rep_device to use from cinder.conf. Could not validate '
                'volume types being added to group.')
            self.assertEqual(expected_msg, e.msg)

    def test_validate_replication_group_config_non_sync_mode(self):
        rep_configs = self.data.multi_rep_config_list
        extra_specs_list = [
            self.data.vol_type_extra_specs_rep_enabled_backend_id_async]
        self.assertRaises(exception.InvalidInput,
                          self.utils.validate_replication_group_config,
                          rep_configs, extra_specs_list)
        try:
            self.utils.validate_replication_group_config(
                rep_configs, extra_specs_list)
        except exception.InvalidInput as e:
            expected_msg = (
                'Invalid input received: Replication for Volume Type is not '
                'set to Synchronous. Only Synchronous can be used with '
                'replication groups')
            self.assertEqual(expected_msg, e.msg)

    @mock.patch.object(utils.PowerMaxUtils, 'get_rep_config')
    def test_validate_replication_group_config_multiple_rep_backend_ids(
            self, mck_get):
        side_effect_list = [
            self.data.rep_config_sync, self.data.rep_config_sync_2]
        mck_get.side_effect = side_effect_list
        rep_configs = self.data.multi_rep_config_list
        ex_specs_1 = deepcopy(
            self.data.vol_type_extra_specs_rep_enabled_backend_id_sync)
        ex_specs_2 = deepcopy(
            self.data.vol_type_extra_specs_rep_enabled_backend_id_sync_2)
        extra_specs_list = [ex_specs_1, ex_specs_2]
        self.assertRaises(exception.InvalidInput,
                          self.utils.validate_replication_group_config,
                          rep_configs, extra_specs_list)
        mck_get.side_effect = side_effect_list
        try:
            self.utils.validate_replication_group_config(
                rep_configs, extra_specs_list)
        except exception.InvalidInput as e:
            expected_msg = (
                'Invalid input received: Multiple replication backend ids '
                'detected please ensure only a single replication device '
                '(backend_id) is used for all Volume Types in a Volume '
                'Group.')
            self.assertEqual(expected_msg, e.msg)

    def test_validate_non_replication_group_config_success(self):
        extra_specs_list = [
            self.data.vol_type_extra_specs]
        self.utils.validate_non_replication_group_config(extra_specs_list)

    def test_validate_non_replication_group_config_failure(self):
        extra_specs = {'pool_name': u'Diamond+DSS+SRP_1+000197800123',
                       utils.IS_RE: '<is> True'}
        self.assertRaises(exception.InvalidInput,
                          self.utils.validate_non_replication_group_config,
                          [extra_specs])
        try:
            self.utils.validate_non_replication_group_config([extra_specs])
        except exception.InvalidInput as e:
            expected_msg = (
                'Invalid input received: Replication is enabled in one or '
                'more of the Volume Types being added to new Volume Group '
                'but the Volume Group is not replication enabled. Please '
                'enable replication in the Volume Group or select only '
                'non-replicated Volume Types.')
            self.assertEqual(expected_msg, e.msg)

    def test_get_migration_delete_extra_specs_replicated(self):
        volume = self.data.test_volume
        metadata = deepcopy(self.data.volume_metadata)
        metadata[utils.IS_RE_CAMEL] = 'True'
        metadata['ReplicationMode'] = utils.REP_SYNC
        metadata['RDFG-Label'] = self.data.rdf_group_name_1
        volume.metadata = metadata
        extra_specs = deepcopy(self.data.extra_specs)
        rep_configs = self.data.multi_rep_config_list
        updated_extra_specs = self.utils.get_migration_delete_extra_specs(
            volume, extra_specs, rep_configs)
        ref_extra_specs = deepcopy(self.data.extra_specs)
        ref_extra_specs[utils.IS_RE] = True
        ref_extra_specs[utils.REP_MODE] = utils.REP_SYNC
        ref_extra_specs[utils.REP_CONFIG] = self.data.rep_config_sync
        ref_extra_specs[utils.REPLICATION_DEVICE_BACKEND_ID] = (
            self.data.rep_backend_id_sync)
        self.assertEqual(ref_extra_specs, updated_extra_specs)

    def test_get_migration_delete_extra_specs_non_replicated(self):
        volume = self.data.test_volume
        volume.metadata = self.data.volume_metadata
        extra_specs = deepcopy(self.data.extra_specs)
        extra_specs[utils.IS_RE] = True
        updated_extra_specs = self.utils.get_migration_delete_extra_specs(
            volume, extra_specs, None)
        self.assertEqual(self.data.extra_specs, updated_extra_specs)

    def test_version_meet_req_true(self):
        version = '9.1.0.14'
        minimum_version = '9.1.0.5'
        self.assertTrue(
            self.utils.version_meet_req(version, minimum_version))

    def test_version_meet_req_false(self):
        version = '9.1.0.3'
        minimum_version = '9.1.0.5'
        self.assertFalse(
            self.utils.version_meet_req(version, minimum_version))

    def test_version_meet_req_major_true(self):
        version = '9.2.0.1'
        minimum_version = '9.1.0.5'
        self.assertTrue(
            self.utils.version_meet_req(version, minimum_version))

    def test_parse_specs_from_pool_name_workload_included(self):
        pool_name = self.data.vol_type_extra_specs.get('pool_name')
        array_id, srp, service_level, workload = (
            self.utils.parse_specs_from_pool_name(pool_name))
        pool_details = pool_name.split('+')
        self.assertEqual(array_id, pool_details[3])
        self.assertEqual(srp, pool_details[2])
        self.assertEqual(workload, pool_details[1])
        self.assertEqual(service_level, pool_details[0])

    def test_parse_specs_from_pool_name_workload_not_included(self):
        pool_name = (
            self.data.vol_type_extra_specs_next_gen_pool.get('pool_name'))
        array_id, srp, service_level, workload = (
            self.utils.parse_specs_from_pool_name(pool_name))

        pool_details = pool_name.split('+')
        self.assertEqual(array_id, pool_details[2])
        self.assertEqual(srp, pool_details[1])
        self.assertEqual(service_level, pool_details[0])
        self.assertEqual(workload, str())

    def test_parse_specs_from_pool_name_invalid_pool(self):
        pool_name = 'This+Is+An+Invalid+Pool'
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.utils.parse_specs_from_pool_name, pool_name)

    def test_parse_specs_from_pool_name_no_pool(self):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.utils.parse_specs_from_pool_name, '')
