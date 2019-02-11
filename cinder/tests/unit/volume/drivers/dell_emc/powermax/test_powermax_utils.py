# Copyright (c) 2017-2019 Dell Inc. or its subsidiaries.
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

from ddt import data
from ddt import ddt
import mock
import six

from cinder import exception
from cinder.objects import fields
from cinder import test
from cinder.tests.unit.volume.drivers.dell_emc.powermax import (
    powermax_data as tpd)
from cinder.tests.unit.volume.drivers.dell_emc.powermax import (
    powermax_fake_objects as tpfo)
from cinder.volume.drivers.dell_emc.powermax import iscsi
from cinder.volume.drivers.dell_emc.powermax import rest
from cinder.volume.drivers.dell_emc.powermax import utils
from cinder.volume import utils as volume_utils
from cinder.volume import volume_types


@ddt
class PowerMaxUtilsTest(test.TestCase):
    def setUp(self):
        self.data = tpd.PowerMaxData()
        volume_utils.get_max_over_subscription_ratio = mock.Mock()
        super(PowerMaxUtilsTest, self).setUp()
        configuration = tpfo.FakeConfiguration(
            None, 'UtilsTests', 1, 1, san_ip='1.1.1.1', san_login='smc',
            vmax_array=self.data.array, vmax_srp='SRP_1', san_password='smc',
            san_api_port=8443, vmax_port_groups=[self.data.port_group_name_i])
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
        extra_specs = self.data.extra_specs_disable_compression
        do_disable_compression = self.utils.is_compression_disabled(
            extra_specs)
        self.assertTrue(do_disable_compression)

    def test_is_compression_disabled_false(self):
        # Path 1: no compression extra spec set
        extra_specs = self.data.extra_specs
        do_disable_compression = self.utils.is_compression_disabled(
            extra_specs)
        self.assertFalse(do_disable_compression)
        # Path 2: compression extra spec set to false
        extra_specs2 = deepcopy(extra_specs)
        extra_specs2.update({utils.DISABLECOMPRESSION: 'false'})
        do_disable_compression2 = self.utils.is_compression_disabled(
            extra_specs)
        self.assertFalse(do_disable_compression2)

    def test_change_compression_type_true(self):
        source_compr_disabled_true = 'true'
        new_type_compr_disabled = {
            'extra_specs': {utils.DISABLECOMPRESSION: 'no'}}
        ans = self.utils.change_compression_type(
            source_compr_disabled_true, new_type_compr_disabled)
        self.assertTrue(ans)

    def test_change_compression_type_false(self):
        source_compr_disabled_true = True
        new_type_compr_disabled = {
            'extra_specs': {utils.DISABLECOMPRESSION: 'true'}}
        ans = self.utils.change_compression_type(
            source_compr_disabled_true, new_type_compr_disabled)
        self.assertFalse(ans)

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
                             'rdf_group_label': self.data.rdf_group_name}]
        rep_config1 = self.utils.get_replication_config(rep_device_list1)
        self.assertEqual(self.data.remote_array, rep_config1['array'])
        # Success, allow_extend true
        rep_device_list2 = rep_device_list1
        rep_device_list2[0]['allow_extend'] = 'true'
        rep_config2 = self.utils.get_replication_config(rep_device_list2)
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
        rep_config5 = self.utils.get_replication_config(rep_device_list5)
        self.assertEqual(utils.REP_ASYNC, rep_config5['mode'])
        # Success, mode is metro - no other options set
        rep_device_list6 = rep_device_list5
        rep_device_list6[0]['mode'] = 'metro'
        rep_config6 = self.utils.get_replication_config(rep_device_list6)
        self.assertFalse(rep_config6['metro_bias'])
        self.assertFalse(rep_config6['allow_delete_metro'])
        # Success, mode is metro - metro options true
        rep_device_list7 = rep_device_list6
        rep_device_list6[0].update(
            {'allow_delete_metro': 'true', 'metro_use_bias': 'true'})
        rep_config7 = self.utils.get_replication_config(rep_device_list7)
        self.assertTrue(rep_config7['metro_bias'])
        self.assertTrue(rep_config7['allow_delete_metro'])

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

    def test_get_async_rdf_managed_grp_name(self):
        rep_config = {'rdf_group_label': self.data.rdf_group_name,
                      'mode': utils.REP_ASYNC}
        grp_name = self.utils.get_async_rdf_managed_grp_name(rep_config)
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
        self.assertFalse(self.utils.does_vol_need_rdf_management_group(
            self.data.rep_extra_specs))
        extra_specs = deepcopy(self.data.rep_extra_specs)
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
        new_type = {'extra_specs': self.data.extra_specs_rep_enabled}
        self.assertFalse(self.utils.change_replication(True, new_type))
        self.assertTrue(self.utils.change_replication(False, new_type))

    def test_get_child_sg_name(self):
        host_name = 'HostX'
        # Slo and rep enabled
        extra_specs1 = self.data.extra_specs_rep_enabled
        extra_specs1[utils.PORTGROUPNAME] = self.data.port_group_name_f
        child_sg_name, do_disable_compression, rep_enabled, pg_name = (
            self.utils.get_child_sg_name(host_name, extra_specs1))
        re_name = self.data.storagegroup_name_f + '-RE'
        self.assertEqual(re_name, child_sg_name)
        # Disable compression
        extra_specs2 = self.data.extra_specs_disable_compression
        extra_specs2[utils.PORTGROUPNAME] = self.data.port_group_name_f
        child_sg_name, do_disable_compression, rep_enabled, pg_name = (
            self.utils.get_child_sg_name(host_name, extra_specs2))
        cd_name = self.data.storagegroup_name_f + '-CD'
        self.assertEqual(cd_name, child_sg_name)
        # No slo
        extra_specs3 = deepcopy(self.data.extra_specs)
        extra_specs3[utils.SLO] = None
        extra_specs3[utils.PORTGROUPNAME] = self.data.port_group_name_f
        child_sg_name, do_disable_compression, rep_enabled, pg_name = (
            self.utils.get_child_sg_name(host_name, extra_specs3))
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
        device_info_pass = self.data.volume_details_attached
        # Success
        hostname = self.utils.get_volume_attached_hostname(device_info_pass)
        self.assertEqual('HostX', hostname)
        # Fail
        device_info_fail = self.data.volume_details_no_sg
        hostname = self.utils.get_volume_attached_hostname(device_info_fail)
        self.assertIsNone(hostname)
