# Copyright (c) 2016 EMC Corporation, Inc.
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

from cinder import exception
from cinder import test
from cinder.tests.unit.volume.drivers.dell_emc.vnx import fake_exception \
    as storops_ex
from cinder.tests.unit.volume.drivers.dell_emc.vnx import fake_storops \
    as storops
from cinder.tests.unit.volume.drivers.dell_emc.vnx import res_mock
from cinder.tests.unit.volume.drivers.dell_emc.vnx import utils as ut_utils
from cinder.volume.drivers.dell_emc.vnx import common
from cinder.volume.drivers.dell_emc.vnx import utils as vnx_utils
from cinder.volume import volume_types


class FakeDriver(object):

    @vnx_utils.require_consistent_group_snapshot_enabled
    def fake_group_method(self, context, group_or_snap):
        return True


class TestUtils(test.TestCase):
    def setUp(self):
        super(TestUtils, self).setUp()
        self.origin_timeout = common.DEFAULT_TIMEOUT
        common.DEFAULT_TIMEOUT = 0.05

    def tearDown(self):
        super(TestUtils, self).tearDown()
        common.DEFAULT_TIMEOUT = self.origin_timeout

    def test_wait_until(self):
        mock_testmethod = mock.Mock(return_value=True)
        vnx_utils.wait_until(mock_testmethod, interval=0)
        mock_testmethod.assert_has_calls([mock.call()])

    def test_wait_until_with_exception(self):
        mock_testmethod = mock.Mock(
            side_effect=storops_ex.VNXAttachSnapError('Unknown error'))
        mock_testmethod.__name__ = 'test_method'
        self.assertRaises(storops_ex.VNXAttachSnapError,
                          vnx_utils.wait_until,
                          mock_testmethod,
                          timeout=1,
                          interval=0,
                          reraise_arbiter=(
                              lambda ex: not isinstance(
                                  ex, storops_ex.VNXCreateLunError)))
        mock_testmethod.assert_has_calls([mock.call()])

    def test_wait_until_with_params(self):
        mock_testmethod = mock.Mock(return_value=True)
        vnx_utils.wait_until(mock_testmethod,
                             param1=1,
                             param2='test')
        mock_testmethod.assert_has_calls(
            [mock.call(param1=1, param2='test')])
        mock_testmethod.assert_has_calls([mock.call(param1=1, param2='test')])

    @res_mock.mock_driver_input
    def test_retype_need_migration_when_host_changed(self, driver_in):
        volume = driver_in['volume']
        another_host = driver_in['host']
        re = vnx_utils.retype_need_migration(
            volume, None, None, another_host)
        self.assertTrue(re)

    @res_mock.mock_driver_input
    def test_retype_need_migration_for_smp_volume(self, driver_in):
        volume = driver_in['volume']
        host = driver_in['host']
        re = vnx_utils.retype_need_migration(
            volume, None, None, host)
        self.assertTrue(re)

    @res_mock.mock_driver_input
    def test_retype_need_migration_when_provision_changed(
            self, driver_in):
        volume = driver_in['volume']
        host = driver_in['host']
        old_spec = common.ExtraSpecs({'provisioning:type': 'thin'})
        new_spec = common.ExtraSpecs({'provisioning:type': 'deduplicated'})
        re = vnx_utils.retype_need_migration(
            volume, old_spec.provision, new_spec.provision, host)
        self.assertTrue(re)

    @res_mock.mock_driver_input
    def test_retype_not_need_migration_when_provision_changed(
            self, driver_in):
        volume = driver_in['volume']
        host = driver_in['host']
        old_spec = common.ExtraSpecs({'provisioning:type': 'thick'})
        new_spec = common.ExtraSpecs({'provisioning:type': 'compressed'})
        re = vnx_utils.retype_need_migration(
            volume, old_spec.provision, new_spec.provision, host)
        self.assertFalse(re)

    @res_mock.mock_driver_input
    def test_retype_not_need_migration(self, driver_in):
        volume = driver_in['volume']
        host = driver_in['host']
        old_spec = common.ExtraSpecs({'storagetype:tiering': 'auto'})
        new_spec = common.ExtraSpecs(
            {'storagetype:tiering': 'starthighthenauto'})
        re = vnx_utils.retype_need_migration(
            volume, old_spec.provision, new_spec.provision, host)
        self.assertFalse(re)

    def test_retype_need_change_tier(self):
        re = vnx_utils.retype_need_change_tier(
            storops.VNXTieringEnum.AUTO, storops.VNXTieringEnum.HIGH_AUTO)
        self.assertTrue(re)

    def test_retype_need_turn_on_compression(self):
        re = vnx_utils.retype_need_turn_on_compression(
            storops.VNXProvisionEnum.THIN,
            storops.VNXProvisionEnum.COMPRESSED)
        self.assertTrue(re)
        re = vnx_utils.retype_need_turn_on_compression(
            storops.VNXProvisionEnum.THICK,
            storops.VNXProvisionEnum.COMPRESSED)
        self.assertTrue(re)

    def test_retype_not_need_turn_on_compression(self):
        re = vnx_utils.retype_need_turn_on_compression(
            storops.VNXProvisionEnum.DEDUPED,
            storops.VNXProvisionEnum.COMPRESSED)
        self.assertFalse(re)
        re = vnx_utils.retype_need_turn_on_compression(
            storops.VNXProvisionEnum.DEDUPED,
            storops.VNXProvisionEnum.COMPRESSED)
        self.assertFalse(re)

    @res_mock.mock_driver_input
    def test_get_base_lun_name(self, mocked):
        volume = mocked['volume']
        self.assertEqual(
            'test',
            vnx_utils.get_base_lun_name(volume))

    def test_convert_to_tgt_list_and_itor_tgt_map(self):
        zone_mapping = {
            'san_1': {'initiator_port_wwn_list':
                      ['wwn1_1'],
                      'target_port_wwn_list':
                      ['wwnt_1', 'wwnt_2']},
            'san_2': {'initiator_port_wwn_list':
                      ['wwn2_1', 'wwn2_2'],
                      'target_port_wwn_list':
                      ['wwnt_1', 'wwnt_3']},
        }

        tgt_wwns, itor_tgt_map = (
            vnx_utils.convert_to_tgt_list_and_itor_tgt_map(zone_mapping))
        self.assertEqual({'wwnt_1', 'wwnt_2', 'wwnt_3'}, set(tgt_wwns))
        self.assertEqual({'wwn1_1': ['wwnt_1', 'wwnt_2'],
                          'wwn2_1': ['wwnt_1', 'wwnt_3'],
                          'wwn2_2': ['wwnt_1', 'wwnt_3']},
                         itor_tgt_map)

    @ut_utils.patch_group_specs('<is> True')
    @res_mock.mock_driver_input
    def test_require_consistent_group_snapshot_enabled(self, input):
        driver = FakeDriver()
        is_called = driver.fake_group_method('context', input['group'])
        self.assertTrue(is_called)

    @res_mock.mock_driver_input
    def test_is_image_cache_volume_false(self, mocked):
        volume = mocked['volume']
        volume.display_name = 'volume-ca86b9a0-d0d5-4267-8cd5-c62274056cc0'
        self.assertFalse(vnx_utils.is_image_cache_volume(volume))
        volume.display_name = 'volume-ca86b9a0-d0d5-c62274056cc0'
        self.assertFalse(vnx_utils.is_image_cache_volume(volume))

    @res_mock.mock_driver_input
    def test_is_image_cache_volume_true(self, mocked):
        volume = mocked['volume']
        volume.display_name = 'image-ca86b9a0-d0d5-4267-8cd5-c62274056cc0'
        self.assertTrue(vnx_utils.is_image_cache_volume(volume))

    @res_mock.mock_driver_input
    def test_calc_migrate_and_provision_image_cache(self, mocked):
        volume = mocked['volume']
        volume.display_name = 'image-ca86b9a0-d0d5-4267-8cd5-c62274056cc0'
        self.assertTrue(vnx_utils.is_image_cache_volume(volume))
        async_migrate, provision = vnx_utils.calc_migrate_and_provision(volume)
        self.assertFalse(async_migrate)
        self.assertEqual(provision.name, 'THIN')

    @res_mock.mock_driver_input
    def test_calc_migrate_and_provision(self, mocked):
        volume = mocked['volume']
        volume.display_name = 'volume-ca86b9a0-d0d5-4267-8cd5-c62274056cc0'
        async_migrate, provision = vnx_utils.calc_migrate_and_provision(volume)
        self.assertEqual(vnx_utils.is_async_migrate_enabled(volume),
                         async_migrate)
        self.assertEqual(provision.name, 'THICK')

    @ut_utils.patch_extra_specs({})
    @res_mock.mock_driver_input
    def test_get_backend_qos_specs(self, cinder_input):
        volume = cinder_input['volume']
        with mock.patch.object(volume_types, 'get_volume_type_qos_specs',
                               return_value={'qos_specs': None}):
            r = vnx_utils.get_backend_qos_specs(volume)
            self.assertIsNone(r)

        with mock.patch.object(volume_types, 'get_volume_type_qos_specs',
                               return_value={
                'qos_specs': {'consumer': 'frontend'}}):
            r = vnx_utils.get_backend_qos_specs(volume)
            self.assertIsNone(r)

        with mock.patch.object(volume_types, 'get_volume_type_qos_specs',
                               return_value={
                'qos_specs': {'id': 'test', 'consumer': 'back-end', 'specs': {
                    common.QOS_MAX_BWS: 100, common.QOS_MAX_IOPS: 10}}}):
            r = vnx_utils.get_backend_qos_specs(volume)
            self.assertIsNotNone(r)
            self.assertEqual(100, r[common.QOS_MAX_BWS])
            self.assertEqual(10, r[common.QOS_MAX_IOPS])

    @ut_utils.patch_group_specs({
        'consistent_group_replication_enabled': '<is> True'})
    @ut_utils.patch_extra_specs({
        'replication_enabled': '<is> False'})
    @res_mock.mock_driver_input
    def test_check_type_matched_invalid(self, mocked):
        volume = mocked['volume']
        volume.group = mocked['group']
        self.assertRaises(exception.InvalidInput,
                          vnx_utils.check_type_matched,
                          volume)

    @ut_utils.patch_group_specs({
        'consistent_group_replication_enabled': '<is> True'})
    @res_mock.mock_driver_input
    def test_check_rep_status_matched_disabled(self, mocked):
        group = mocked['group']
        self.assertRaises(exception.InvalidInput,
                          vnx_utils.check_rep_status_matched,
                          group)
