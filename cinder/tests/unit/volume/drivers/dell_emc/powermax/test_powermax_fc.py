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
from cinder.tests.unit.volume.drivers.dell_emc.powermax import (
    powermax_data as tpd)
from cinder.tests.unit.volume.drivers.dell_emc.powermax import (
    powermax_fake_objects as tpfo)
from cinder.volume.drivers.dell_emc.powermax import common
from cinder.volume.drivers.dell_emc.powermax import fc
from cinder.volume.drivers.dell_emc.powermax import rest
from cinder.volume import volume_utils
from cinder.zonemanager import utils as fczm_utils


class PowerMaxFCTest(test.TestCase):
    def setUp(self):
        self.data = tpd.PowerMaxData()
        super(PowerMaxFCTest, self).setUp()
        volume_utils.get_max_over_subscription_ratio = mock.Mock()
        self.configuration = tpfo.FakeConfiguration(
            None, 'FCTests', 1, 1, san_ip='1.1.1.1', san_login='smc',
            powermax_array=self.data.array, powermax_srp='SRP_1',
            san_password='smc', san_api_port=8443,
            powermax_port_groups=[self.data.port_group_name_i])
        rest.PowerMaxRest._establish_rest_session = mock.Mock(
            return_value=tpfo.FakeRequestsSession())
        driver = fc.PowerMaxFCDriver(configuration=self.configuration)
        self.driver = driver
        self.common = self.driver.common
        self.masking = self.common.masking
        self.utils = self.common.utils
        self.utils.get_volumetype_extra_specs = (
            mock.Mock(return_value=self.data.vol_type_extra_specs))

    def test_create_volume(self):
        with mock.patch.object(self.common, 'create_volume') as mock_create:
            self.driver.create_volume(self.data.test_volume)
            mock_create.assert_called_once_with(self.data.test_volume)

    def test_create_volume_from_snapshot(self):
        volume = self.data.test_clone_volume
        snapshot = self.data.test_snapshot
        with mock.patch.object(
                self.common, 'create_volume_from_snapshot') as mock_create:
            self.driver.create_volume_from_snapshot(volume, snapshot)
            mock_create.assert_called_once_with(volume, snapshot)

    def test_create_cloned_volume(self):
        volume = self.data.test_clone_volume
        src_volume = self.data.test_volume
        with mock.patch.object(
                self.common, 'create_cloned_volume') as mock_create:
            self.driver.create_cloned_volume(volume, src_volume)
            mock_create.assert_called_once_with(volume, src_volume)

    def test_delete_volume(self):
        with mock.patch.object(self.common, 'delete_volume') as mock_delete:
            self.driver.delete_volume(self.data.test_volume)
            mock_delete.assert_called_once_with(self.data.test_volume)

    def test_create_snapshot(self):
        with mock.patch.object(self.common, 'create_snapshot') as mock_create:
            self.driver.create_snapshot(self.data.test_snapshot)
            mock_create.assert_called_once_with(
                self.data.test_snapshot, self.data.test_snapshot.volume)

    def test_delete_snapshot(self):
        with mock.patch.object(self.common, 'delete_snapshot') as mock_delete:
            self.driver.delete_snapshot(self.data.test_snapshot)
            mock_delete.assert_called_once_with(
                self.data.test_snapshot, self.data.test_snapshot.volume)

    def test_initialize_connection(self):
        with mock.patch.object(
                self.common, 'initialize_connection',
                return_value=self.data.fc_device_info) as mock_initialize:
            with mock.patch.object(
                    self.driver, 'populate_data') as mock_populate:
                self.driver.initialize_connection(
                    self.data.test_volume, self.data.connector)
                mock_initialize.assert_called_once_with(
                    self.data.test_volume, self.data.connector)
                mock_populate.assert_called_once_with(
                    self.data.fc_device_info, self.data.test_volume,
                    self.data.connector)

    def test_populate_data(self):
        with mock.patch.object(self.driver, '_build_initiator_target_map',
                               return_value=([], {})) as mock_build:
            ref_data = {
                'driver_volume_type': 'fibre_channel',
                'data': {'target_lun': self.data.fc_device_info['hostlunid'],
                         'target_discovered': True,
                         'target_wwn': [],
                         'initiator_target_map': {}}}
            data = self.driver.populate_data(self.data.fc_device_info,
                                             self.data.test_volume,
                                             self.data.connector)
            self.assertEqual(ref_data, data)
            mock_build.assert_called_once_with(
                self.data.test_volume, self.data.connector,
                self.data.fc_device_info)

    def test_terminate_connection(self):
        with mock.patch.object(
                self.common, 'terminate_connection') as mock_terminate:
            self.driver.terminate_connection(
                self.data.test_volume, self.data.connector)
            mock_terminate.assert_called_once_with(
                self.data.test_volume, self.data.connector)

    def test_terminate_connection_no_zoning_mappings(self):
        with mock.patch.object(self.driver, '_get_zoning_mappings',
                               return_value=None):
            with mock.patch.object(
                    self.common, 'terminate_connection') as mock_terminate:
                self.driver.terminate_connection(self.data.test_volume,
                                                 self.data.connector)
                mock_terminate.assert_not_called()

    def test_get_zoning_mappings(self):
        ref_mappings = self.data.zoning_mappings
        zoning_mappings = self.driver._get_zoning_mappings(
            self.data.test_volume, self.data.connector)
        self.assertEqual(ref_mappings, zoning_mappings)
        # Legacy vol
        zoning_mappings2 = self.driver._get_zoning_mappings(
            self.data.test_legacy_vol, self.data.connector)
        self.assertEqual(ref_mappings, zoning_mappings2)

    def test_get_zoning_mappings_no_mv(self):
        with mock.patch.object(self.common, 'get_masking_views_from_volume',
                               return_value=(None, False)):
            zoning_mappings = self.driver._get_zoning_mappings(
                self.data.test_volume, self.data.connector)
            self.assertEqual({}, zoning_mappings)

    @mock.patch.object(
        common.PowerMaxCommon, 'get_masking_views_from_volume',
        side_effect = ([(None, False),
                        ([tpd.PowerMaxData.masking_view_name_f], False)]))
    def test_get_zoning_mappings_retry_backward_compatibility(
            self, mock_views):
        with mock.patch.object(self.common.utils, 'get_host_name_label',
                               return_value=None) as mock_label:
            self.driver._get_zoning_mappings(
                self.data.test_volume, self.data.connector)
            self.assertEqual(2, mock_label.call_count)
            self.assertEqual(2, mock_views.call_count)

    @mock.patch.object(
        common.PowerMaxCommon, 'get_masking_views_from_volume',
        return_value=([tpd.PowerMaxData.masking_view_name_f], True))
    def test_get_zoning_mappings_metro(self, mock_mv):
        ref_mappings = self.data.zoning_mappings_metro
        zoning_mappings = self.driver._get_zoning_mappings(
            self.data.test_volume, self.data.connector)
        self.assertEqual(ref_mappings, zoning_mappings)

    def test_cleanup_zones_other_vols_mapped(self):
        ref_data = {'driver_volume_type': 'fibre_channel',
                    'data': {}}
        data = self.driver._cleanup_zones(self.data.zoning_mappings)
        self.assertEqual(ref_data, data)

    def test_cleanup_zones_no_vols_mapped(self):
        zoning_mappings = self.data.zoning_mappings
        ref_data = {'driver_volume_type': 'fibre_channel',
                    'data': {'target_wwn': zoning_mappings['target_wwns'],
                             'initiator_target_map':
                                 zoning_mappings['init_targ_map']}}
        with mock.patch.object(self.common, 'get_common_masking_views',
                               return_value=[]):
            data = self.driver._cleanup_zones(self.data.zoning_mappings)
            self.assertEqual(ref_data, data)

    def test_build_initiator_target_map_default(self):
        ref_target_map = {'123456789012345': ['543210987654321'],
                          '123456789054321': ['123450987654321']}
        with mock.patch.object(fczm_utils, 'create_lookup_service',
                               return_value=tpfo.FakeLookupService()):
            driver = fc.PowerMaxFCDriver(configuration=self.configuration)
            with mock.patch.object(driver.common,
                                   'get_target_wwns_from_masking_view',
                                   return_value=(self.data.target_wwns, [])):
                targets, target_map = driver._build_initiator_target_map(
                    self.data.test_volume, self.data.connector)
                self.assertEqual(ref_target_map, target_map)

    def test_build_initiator_target_map_load_balanced(self):
        init_wwns = self.data.connector.get('wwpns')
        init_a, init_b = init_wwns[0], init_wwns[1]
        self.driver.performance.config = self.data.performance_config
        with mock.patch.object(
                self.common, 'get_target_wwns_from_masking_view',
                return_value=(self.data.target_wwns_multi, [])):
            targets, target_map = self.driver._build_initiator_target_map(
                self.data.test_volume, self.data.connector,
                device_info=self.data.iscsi_device_info)
            self.assertEqual(1, len(target_map.get(init_a)))
            self.assertEqual(1, len(target_map.get(init_b)))
            self.assertTrue(
                len(target_map.get(init_a)) < len(self.data.target_wwns_multi))
            self.assertTrue(
                len(target_map.get(init_b)) < len(self.data.target_wwns_multi))

    def test_build_initiator_target_map_load_balanced_exception(self):
        ref_target_map = {'123456789012345': self.data.target_wwns_multi,
                          '123456789054321': self.data.target_wwns_multi}
        self.driver.performance.config = self.data.performance_config
        with mock.patch.object(
            self.common, 'get_target_wwns_from_masking_view',
                return_value=(self.data.target_wwns_multi, [])) as mck_wwns:
            with mock.patch.object(
                self.driver.performance, 'process_port_load',
                    side_effect=exception.VolumeBackendAPIException('')):
                targets, target_map = self.driver._build_initiator_target_map(
                    self.data.test_volume, self.data.connector,
                    device_info=self.data.iscsi_device_info)
                self.assertEqual(ref_target_map, target_map)
                self.assertEqual(mck_wwns.call_count, 2)

    def test_extend_volume(self):
        with mock.patch.object(self.common, 'extend_volume') as mock_extend:
            self.driver.extend_volume(self.data.test_volume, '3')
            mock_extend.assert_called_once_with(self.data.test_volume, '3')

    def test_get_volume_stats(self):
        with mock.patch.object(
                self.driver, '_update_volume_stats') as mock_update:

            # with refresh
            self.driver.get_volume_stats(True)

            # set fake stats
            self.driver._stats['driver_version'] = self.driver.VERSION
            # no refresh
            self.driver.get_volume_stats()

            mock_update.assert_called_once_with()

    def test_update_volume_stats(self):
        with mock.patch.object(self.common, 'update_volume_stats',
                               return_value={}) as mock_update:
            self.driver._update_volume_stats()
            mock_update.assert_called_once_with()

    def test_check_for_setup_error(self):
        self.driver.check_for_setup_error()

    def test_ensure_export(self):
        self.driver.ensure_export('context', 'volume')

    def test_create_export(self):
        self.driver.create_export('context', 'volume', 'connector')

    def test_remove_export(self):
        self.driver.remove_export('context', 'volume')

    def test_check_for_export(self):
        self.driver.check_for_export('context', 'volume_id')

    def test_manage_existing(self):
        with mock.patch.object(self.common, 'manage_existing',
                               return_value={}) as mock_manage:
            external_ref = {u'source-name': u'00002'}
            self.driver.manage_existing(self.data.test_volume, external_ref)
            mock_manage.assert_called_once_with(
                self.data.test_volume, external_ref)

    def test_manage_existing_get_size(self):
        with mock.patch.object(self.common, 'manage_existing_get_size',
                               return_value='1') as mock_manage:
            external_ref = {u'source-name': u'00002'}
            self.driver.manage_existing_get_size(
                self.data.test_volume, external_ref)
            mock_manage.assert_called_once_with(
                self.data.test_volume, external_ref)

    def test_unmanage_volume(self):
        with mock.patch.object(self.common, 'unmanage',
                               return_value={}) as mock_unmanage:
            self.driver.unmanage(self.data.test_volume)
            mock_unmanage.assert_called_once_with(
                self.data.test_volume)

    def test_retype(self):
        host = {'host': self.data.new_host}
        new_type = {'extra_specs': {}}
        with mock.patch.object(self.common, 'retype',
                               return_value=True) as mck_retype:
            self.driver.retype({}, self.data.test_volume, new_type, '', host)
            mck_retype.assert_called_once_with(
                self.data.test_volume, new_type, host)

    def test_failover_host(self):
        with mock.patch.object(
                self.common, 'failover_host',
                return_value=(self.data.remote_array, [], [])) as mock_fo:
            self.driver.failover_host(self.data.ctx, [self.data.test_volume])
            mock_fo.assert_called_once_with([self.data.test_volume], None,
                                            None)

    def test_enable_replication(self):
        with mock.patch.object(
                self.common, 'enable_replication') as mock_er:
            self.driver.enable_replication(
                self.data.ctx, self.data.test_group, [self.data.test_volume])
            mock_er.assert_called_once()

    def test_disable_replication(self):
        with mock.patch.object(
                self.common, 'disable_replication') as mock_dr:
            self.driver.disable_replication(
                self.data.ctx, self.data.test_group, [self.data.test_volume])
            mock_dr.assert_called_once()

    def test_failover_replication(self):
        with mock.patch.object(
                self.common, 'failover_replication') as mock_fo:
            self.driver.failover_replication(
                self.data.ctx, self.data.test_group, [self.data.test_volume])
            mock_fo.assert_called_once()
