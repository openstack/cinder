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

import ast
from copy import deepcopy
import mock
import six

from cinder import exception
from cinder.objects import fields
from cinder import test
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit.volume.drivers.dell_emc.powermax import (
    powermax_data as tpd)
from cinder.tests.unit.volume.drivers.dell_emc.powermax import (
    powermax_fake_objects as tpfo)
from cinder.volume.drivers.dell_emc.powermax import common
from cinder.volume.drivers.dell_emc.powermax import fc
from cinder.volume.drivers.dell_emc.powermax import masking
from cinder.volume.drivers.dell_emc.powermax import provision
from cinder.volume.drivers.dell_emc.powermax import rest
from cinder.volume.drivers.dell_emc.powermax import utils
from cinder.volume import utils as volume_utils


class PowerMaxCommonTest(test.TestCase):
    def setUp(self):
        self.data = tpd.PowerMaxData()
        super(PowerMaxCommonTest, self).setUp()
        self.mock_object(volume_utils, 'get_max_over_subscription_ratio',
                         return_value=1.0)
        configuration = tpfo.FakeConfiguration(
            None, 'CommonTests', 1, 1, san_ip='1.1.1.1', san_login='smc',
            vmax_array=self.data.array, vmax_srp='SRP_1', san_password='smc',
            san_api_port=8443, vmax_port_groups=[self.data.port_group_name_f])
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

    @mock.patch.object(rest.PowerMaxRest, 'set_rest_credentials')
    @mock.patch.object(common.PowerMaxCommon, '_get_slo_workload_combinations',
                       return_value=[])
    @mock.patch.object(
        common.PowerMaxCommon, 'get_attributes_from_cinder_config',
        return_value=[])
    def test_gather_info_no_opts(self, mock_parse, mock_combo, mock_rest):
        configuration = tpfo.FakeConfiguration(
            None, 'config_group', None, None)
        fc.PowerMaxFCDriver(configuration=configuration)

    @mock.patch.object(rest.PowerMaxRest, 'get_array_model_info',
                       return_value=('PowerMax 2000', True))
    @mock.patch.object(rest.PowerMaxRest, 'set_rest_credentials')
    @mock.patch.object(common.PowerMaxCommon, '_get_slo_workload_combinations',
                       return_value=[])
    @mock.patch.object(
        common.PowerMaxCommon, 'get_attributes_from_cinder_config',
        return_value=tpd.PowerMaxData.array_info_wl)
    def test_gather_info_next_gen(self, mock_parse, mock_combo, mock_rest,
                                  mock_nextgen):
        self.common._gather_info()
        self.assertTrue(self.common.next_gen)

    def test_get_slo_workload_combinations_powermax(self):
        array_info = self.common.get_attributes_from_cinder_config()
        finalarrayinfolist = self.common._get_slo_workload_combinations(
            array_info)
        self.assertTrue(len(finalarrayinfolist) > 1)

    @mock.patch.object(
        rest.PowerMaxRest, 'get_vmax_model',
        return_value=(tpd.PowerMaxData.vmax_model_details['model']))
    @mock.patch.object(
        rest.PowerMaxRest, 'get_slo_list',
        return_value=(tpd.PowerMaxData.vmax_slo_details['sloId']))
    def test_get_slo_workload_combinations_vmax(self, mck_slo, mck_model):
        array_info = self.common.get_attributes_from_cinder_config()
        finalarrayinfolist = self.common._get_slo_workload_combinations(
            array_info)
        self.assertTrue(len(finalarrayinfolist) > 1)

    @mock.patch.object(
        rest.PowerMaxRest, 'get_vmax_model',
        return_value=tpd.PowerMaxData.powermax_model_details['model'])
    @mock.patch.object(rest.PowerMaxRest, 'get_workload_settings',
                       return_value=[])
    @mock.patch.object(
        rest.PowerMaxRest, 'get_slo_list',
        return_value=tpd.PowerMaxData.powermax_slo_details['sloId'])
    def test_get_slo_workload_combinations_next_gen(self, mck_slo, mck_wl,
                                                    mck_model):
        self.common.next_gen = True
        self.common.array_model = 'PowerMax 2000'
        finalarrayinfolist = self.common._get_slo_workload_combinations(
            self.data.array_info_no_wl)
        self.assertTrue(len(finalarrayinfolist) == 14)

    @mock.patch.object(
        rest.PowerMaxRest, 'get_vmax_model',
        return_value=tpd.PowerMaxData.vmax_model_details['model'])
    @mock.patch.object(rest.PowerMaxRest, 'get_workload_settings',
                       return_value=[])
    @mock.patch.object(
        rest.PowerMaxRest, 'get_slo_list',
        return_value=tpd.PowerMaxData.powermax_slo_details['sloId'])
    def test_get_slo_workload_combinations_next_gen_vmax(
            self, mck_slo, mck_wl, mck_model):
        self.common.next_gen = True
        finalarrayinfolist = self.common._get_slo_workload_combinations(
            self.data.array_info_no_wl)
        self.assertTrue(len(finalarrayinfolist) == 18)

    def test_get_slo_workload_combinations_failed(self):
        array_info = {}
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.common._get_slo_workload_combinations, array_info)

    def test_create_volume(self):
        ref_model_update = (
            {'provider_location': six.text_type(self.data.provider_location)})
        model_update = self.common.create_volume(self.data.test_volume)
        self.assertEqual(ref_model_update, model_update)

    def test_create_volume_qos(self):
        ref_model_update = (
            {'provider_location': six.text_type(self.data.provider_location)})
        extra_specs = deepcopy(self.data.extra_specs_intervals_set)
        extra_specs['qos'] = {
            'total_iops_sec': '4000', 'DistributionType': 'Always'}
        with mock.patch.object(self.utils, 'get_volumetype_extra_specs',
                               return_value=extra_specs):
            model_update = self.common.create_volume(self.data.test_volume)
            self.assertEqual(ref_model_update, model_update)

    def test_create_volume_from_snapshot(self):
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

    def test_cloned_volume(self):
        ref_model_update = ({'provider_location': six.text_type(
            self.data.provider_location_clone)})
        model_update = self.common.create_cloned_volume(
            self.data.test_clone_volume, self.data.test_volume)
        self.assertEqual(
            ast.literal_eval(ref_model_update['provider_location']),
            ast.literal_eval(model_update['provider_location']))

    def test_delete_volume(self):
        with mock.patch.object(self.common, '_delete_volume') as mock_delete:
            self.common.delete_volume(self.data.test_volume)
            mock_delete.assert_called_once_with(self.data.test_volume)

    def test_create_snapshot(self):
        ref_model_update = ({'provider_location': six.text_type(
            self.data.snap_location)})
        model_update = self.common.create_snapshot(
            self.data.test_snapshot, self.data.test_volume)
        self.assertEqual(ref_model_update, model_update)

    def test_delete_snapshot(self):
        snap_name = self.data.snap_location['snap_name']
        sourcedevice_id = self.data.snap_location['source_id']
        generation = 0
        with mock.patch.object(
                self.provision, 'delete_volume_snap') as mock_delete_snap:
            self.common.delete_snapshot(
                self.data.test_snapshot, self.data.test_volume)
            mock_delete_snap.assert_called_once_with(
                self.data.array, snap_name, [sourcedevice_id],
                restored=False, generation=generation)

    def test_delete_snapshot_not_found(self):
        with mock.patch.object(self.common, '_parse_snap_info',
                               return_value=(None, 'Something')):
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
            extra_specs, True, self.data.connector, async_grp=None)

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
            extra_specs, False, self.data.connector, async_grp=None)
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
                connector, False, async_grp=None)

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
                    connector, False, async_grp=None)

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
                False, async_grp=None)

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

    @mock.patch.object(rest.PowerMaxRest, 'is_next_gen_array',
                       return_value=True)
    @mock.patch.object(common.PowerMaxCommon, '_sync_check')
    @mock.patch.object(provision.PowerMaxProvision, 'extend_volume')
    def test_extend_volume_success(self, mock_extend, mock_sync, mock_newgen):
        volume = self.data.test_volume
        array = self.data.array
        device_id = self.data.device_id
        new_size = self.data.test_volume.size
        ref_extra_specs = deepcopy(self.data.extra_specs_intervals_set)
        ref_extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        with mock.patch.object(self.rest, 'is_vol_in_rep_session',
                               side_effect=[(False, False, None),
                                            (False, True, None)]):
            self.common.extend_volume(volume, new_size)
            mock_extend.assert_called_once_with(
                array, device_id, new_size, ref_extra_specs)
            # Success, with snapshot, on new VMAX array
            mock_extend.reset_mock()
            self.common.extend_volume(volume, new_size)
            mock_extend.assert_called_once_with(
                array, device_id, new_size, ref_extra_specs)

    def test_extend_volume_failed_snap_src(self):
        volume = self.data.test_volume
        new_size = self.data.test_volume.size
        with mock.patch.object(self.rest, 'is_vol_in_rep_session',
                               return_value=(False, True, None)):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.common.extend_volume, volume, new_size)

    def test_extend_volume_failed_no_device_id(self):
        volume = self.data.test_volume
        new_size = self.data.test_volume.size
        with mock.patch.object(self.common, '_find_device_on_array',
                               return_value=None):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.common.extend_volume, volume, new_size)

    def test_extend_volume_failed_wrong_size(self):
        volume = self.data.test_volume
        new_size = 1
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
        return_value=([], [tpd.PowerMaxData.masking_view_name_f]))
    def test_find_host_lun_id_multiattach(self, mock_mask):
        volume = self.data.test_volume
        extra_specs = self.data.extra_specs
        __, is_multiattach = self.common.find_host_lun_id(
            volume, 'HostX', extra_specs)
        self.assertTrue(is_multiattach)

    @mock.patch.object(common.PowerMaxCommon, 'get_remote_target_device',
                       return_value=tpd.PowerMaxData.device_id2)
    @mock.patch.object(rest.PowerMaxRest, 'get_volume',
                       return_value=tpd.PowerMaxData.volume_details[0])
    def test_find_host_lun_id_rep_extra_specs(self, mock_vol, mock_tgt):
        self.common.find_host_lun_id(
            self.data.test_volume, 'HostX',
            self.data.extra_specs, self.data.rep_extra_specs)
        mock_tgt.assert_called_once()

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

    @mock.patch.object(common.PowerMaxCommon, 'get_remote_target_device',
                       return_value=tpd.PowerMaxData.device_id2)
    def test_populate_masking_dict(self, mock_tgt):
        volume = self.data.test_volume
        connector = self.data.connector
        extra_specs = deepcopy(self.data.extra_specs)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        extra_specs[utils.WORKLOAD] = self.data.workload
        ref_mv_dict = self.data.masking_view_dict
        self.common.next_gen = False
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

    def test_create_cloned_volume(self):
        volume = self.data.test_clone_volume
        source_volume = self.data.test_volume
        extra_specs = self.data.extra_specs
        ref_dict = self.data.provider_location_clone
        clone_dict = self.common._create_cloned_volume(
            volume, source_volume, extra_specs)
        self.assertEqual(ref_dict, clone_dict)

    def test_create_cloned_volume_is_snapshot(self):
        volume = self.data.test_snapshot
        source_volume = self.data.test_volume
        extra_specs = self.data.extra_specs
        ref_dict = self.data.snap_location
        clone_dict = self.common._create_cloned_volume(
            volume, source_volume, extra_specs, True, False)
        self.assertEqual(ref_dict, clone_dict)

    def test_create_cloned_volume_from_snapshot(self):
        volume = self.data.test_clone_volume
        source_volume = self.data.test_snapshot
        extra_specs = self.data.extra_specs
        ref_dict = self.data.provider_location_snapshot
        clone_dict = self.common._create_cloned_volume(
            volume, source_volume, extra_specs, False, True)
        self.assertEqual(ref_dict, clone_dict)

    def test_create_cloned_volume_not_licenced(self):
        volume = self.data.test_clone_volume
        source_volume = self.data.test_volume
        extra_specs = self.data.extra_specs
        with mock.patch.object(self.rest, 'is_snapvx_licensed',
                               return_value=False):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.common._create_cloned_volume,
                              volume, source_volume, extra_specs)

    def test_parse_snap_info_found(self):
        ref_device_id = self.data.device_id
        ref_snap_name = self.data.snap_location['snap_name']
        sourcedevice_id, foundsnap_name = self.common._parse_snap_info(
            self.data.array, self.data.test_snapshot)
        self.assertEqual(ref_device_id, sourcedevice_id)
        self.assertEqual(ref_snap_name, foundsnap_name)

    def test_parse_snap_info_not_found(self):
        ref_snap_name = None
        with mock.patch.object(self.rest, 'get_volume_snap',
                               return_value=None):
            __, foundsnap_name = self.common._parse_snap_info(
                self.data.array, self.data.test_snapshot)
            self.assertIsNone(ref_snap_name, foundsnap_name)

    def test_parse_snap_info_exception(self):
        with mock.patch.object(
                self.rest, 'get_volume_snap',
                side_effect=exception.VolumeBackendAPIException):
            __, foundsnap_name = self.common._parse_snap_info(
                self.data.array, self.data.test_snapshot)
            self.assertIsNone(foundsnap_name)

    def test_parse_snap_info_provider_location_not_string(self):
        snapshot = fake_snapshot.fake_snapshot_obj(
            context='ctxt', provider_loaction={'not': 'string'})
        sourcedevice_id, foundsnap_name = self.common._parse_snap_info(
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

    @mock.patch.object(masking.PowerMaxMasking,
                       'remove_vol_from_storage_group')
    def test_delete_volume_from_srp(self, mock_rm):
        array = self.data.array
        device_id = self.data.device_id
        volume_name = self.data.test_volume.name
        ref_extra_specs = self.data.extra_specs_intervals_set
        ref_extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        volume = self.data.test_volume
        with mock.patch.object(self.common, '_sync_check'):
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
        volume_name = '1'
        volume_size = self.data.test_volume.size
        extra_specs = self.data.extra_specs
        ref_dict = self.data.provider_location
        with mock.patch.object(self.rest, 'get_volume',
                               return_value=self.data.volume_details[0]):
            volume_dict = self.common._create_volume(
                volume_name, volume_size, extra_specs)
        self.assertEqual(ref_dict, volume_dict)

    def test_create_volume_success_next_gen(self):
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
                        volume_name, volume_size, extra_specs)
                    mock_get.assert_called_once_with(
                        extra_specs['array'], extra_specs[utils.SRP],
                        extra_specs[utils.SLO], 'NONE', extra_specs, True,
                        False, None)

    def test_create_volume_failed(self):
        volume_name = self.data.test_volume.name
        volume_size = self.data.test_volume.size
        extra_specs = self.data.extra_specs
        with mock.patch.object(
                self.masking, 'get_or_create_default_storage_group',
                return_value=self.data.failed_resource):
            with mock.patch.object(
                    self.rest, 'delete_storage_group') as mock_delete:
                # path 1: not last vol in sg
                with mock.patch.object(
                        self.rest, 'get_num_vols_in_sg', return_value=2):
                    self.assertRaises(exception.VolumeBackendAPIException,
                                      self.common._create_volume,
                                      volume_name, volume_size, extra_specs)
                    mock_delete.assert_not_called()
                # path 2: last vol in sg, delete sg
                with mock.patch.object(self.rest, 'get_num_vols_in_sg',
                                       return_value=0):
                    self.assertRaises(exception.VolumeBackendAPIException,
                                      self.common._create_volume,
                                      volume_name, volume_size, extra_specs)
                    mock_delete.assert_called_once_with(
                        self.data.array, self.data.failed_resource)

    def test_create_volume_incorrect_slo(self):
        volume_name = self.data.test_volume.name
        volume_size = self.data.test_volume.size
        extra_specs = {'slo': 'Diamondz',
                       'workload': 'DSSSS',
                       'srp': self.data.srp,
                       'array': self.data.array}
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.common._create_volume,
            volume_name, volume_size, extra_specs)

    @mock.patch.object(rest.PowerMaxRest, 'is_next_gen_array',
                       return_value=False)
    @mock.patch.object(provision.PowerMaxProvision, 'verify_slo_workload',
                       return_value=(True, True))
    @mock.patch.object(provision.PowerMaxProvision, 'create_volume_from_sg')
    def test_create_volume_in_use_replication_enabled(self, mock_create,
                                                      mock_verify,
                                                      mock_nextgen):
        volume_name = '1'
        volume_size = self.data.test_volume.size
        rep_extra_specs = self.data.rep_extra_specs3
        with mock.patch.object(
                self.masking,
                'get_or_create_default_storage_group') as mck_sg:
            self.common._create_volume(
                volume_name, volume_size, rep_extra_specs, in_use=True)
            mck_sg.assert_called_once_with(
                rep_extra_specs['array'], rep_extra_specs['srp'],
                rep_extra_specs['slo'], rep_extra_specs['workload'],
                rep_extra_specs, False, True, rep_extra_specs['rep_mode'])

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
            mock_add.assert_called_once_with(
                array, device_id, volume_name, extra_specs)

    @mock.patch.object(utils.PowerMaxUtils, 'is_replication_enabled',
                       side_effect=[False, True])
    def test_remove_vol_and_cleanup_replication(self, mock_rep_enabled):
        array = self.data.array
        device_id = self.data.device_id
        volume = self.data.test_volume
        volume_name = self.data.test_volume.name
        extra_specs = self.data.extra_specs
        with mock.patch.object(
                self.masking, 'remove_and_reset_members') as mock_rm:
            with mock.patch.object(
                    self.common, 'cleanup_lun_replication') as mock_clean:
                self.common._remove_vol_and_cleanup_replication(
                    array, device_id, volume_name, extra_specs, volume)
                mock_rm.assert_called_once_with(
                    array, volume, device_id, volume_name, extra_specs, False)
                mock_clean.assert_not_called()
                self.common._remove_vol_and_cleanup_replication(
                    array, device_id, volume_name, extra_specs, volume)
                mock_clean.assert_called_once_with(
                    volume, volume_name, device_id, extra_specs)

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
    @mock.patch.object(common.PowerMaxCommon, 'get_remote_target_device',
                       return_value=(tpd.PowerMaxData.device_id2,))
    @mock.patch.object(utils.PowerMaxUtils, 'is_metro_device',
                       side_effect=[False, True])
    def test_get_target_wwns(self, mock_metro, mock_tgt, mock_specs):
        __, metro_wwns = self.common.get_target_wwns_from_masking_view(
            self.data.test_volume, self.data.connector)
        self.assertEqual([], metro_wwns)
        # Is metro volume
        __, metro_wwns = self.common.get_target_wwns_from_masking_view(
            self.data.test_volume, self.data.connector)
        self.assertEqual([self.data.wwnn1], metro_wwns)

    def test_get_port_group_from_masking_view(self):
        array = self.data.array
        maskingview_name = self.data.masking_view_name_f
        with mock.patch.object(
                self.rest, 'get_element_from_masking_view') as mock_get:
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

    def test_get_ip_and_iqn(self):
        ref_ip_iqn = [{'iqn': self.data.initiator,
                       'ip': self.data.ip}]
        port = self.data.portgroup[1]['symmetrixPortKey'][0]['portId']
        ip_iqn_list = self.common._get_ip_and_iqn(self.data.array, port)
        self.assertEqual(ref_ip_iqn, ip_iqn_list)

    def test_find_ip_and_iqns(self):
        ref_ip_iqn = [{'iqn': self.data.initiator,
                       'ip': self.data.ip}]
        ip_iqn_list = self.common._find_ip_and_iqns(
            self.data.array, self.data.port_group_name_i)
        self.assertEqual(ref_ip_iqn, ip_iqn_list)

    def test_create_replica_snap_name(self):
        array = self.data.array
        clone_volume = self.data.test_clone_volume
        source_device_id = self.data.device_id
        snap_name = self.data.snap_location['snap_name']
        ref_dict = self.data.provider_location_snapshot
        clone_dict = self.common._create_replica(
            array, clone_volume, source_device_id,
            self.data.extra_specs, snap_name)
        self.assertEqual(ref_dict, clone_dict)

    def test_create_replica_no_snap_name(self):
        array = self.data.array
        clone_volume = self.data.test_clone_volume
        source_device_id = self.data.device_id
        snap_name = "temp-" + source_device_id + "-snapshot_for_clone"
        ref_dict = self.data.provider_location_clone
        with mock.patch.object(
                self.utils, 'get_temp_snap_name',
                return_value=snap_name) as mock_get_snap:
            clone_dict = self.common._create_replica(
                array, clone_volume, source_device_id,
                self.data.extra_specs)
            self.assertEqual(ref_dict, clone_dict)
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
                extra_specs)

    def test_create_replica_failed_no_target(self):
        array = self.data.array
        clone_volume = self.data.test_clone_volume
        source_device_id = self.data.device_id
        snap_name = self.data.failed_resource
        with mock.patch.object(self.common, '_create_volume',
                               return_value={'device_id': None}):
            with mock.patch.object(
                    self.common, '_cleanup_target') as mock_cleanup:
                self.assertRaises(
                    exception.VolumeBackendAPIException,
                    self.common._create_replica, array, clone_volume,
                    source_device_id, self.data.extra_specs, snap_name)
                mock_cleanup.assert_not_called()

    @mock.patch.object(
        masking.PowerMaxMasking,
        'remove_and_reset_members')
    def test_cleanup_target_sync_present(self, mock_remove):
        array = self.data.array
        clone_volume = self.data.test_clone_volume
        source_device_id = self.data.device_id
        target_device_id = self.data.device_id2
        snap_name = self.data.failed_resource
        clone_name = clone_volume.name
        extra_specs = self.data.extra_specs
        generation = 0
        with mock.patch.object(self.rest, 'get_sync_session',
                               return_value='session'):
            with mock.patch.object(
                    self.provision,
                    'break_replication_relationship') as mock_break:
                self.common._cleanup_target(
                    array, target_device_id, source_device_id,
                    clone_name, snap_name, extra_specs)
                mock_break.assert_called_with(
                    array, target_device_id, source_device_id,
                    snap_name, extra_specs, generation)

    def test_cleanup_target_no_sync(self):
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

    @mock.patch.object(provision.PowerMaxProvision, 'delete_volume_snap')
    @mock.patch.object(provision.PowerMaxProvision,
                       'break_replication_relationship')
    def test_sync_check_temp_snap(self, mock_break, mock_delete):
        array = self.data.array
        device_id = self.data.device_id
        target = self.data.volume_details[1]['volumeId']
        extra_specs = self.data.extra_specs
        snap_name = 'temp-1'
        generation = '0'
        with mock.patch.object(self.rest, 'get_volume_snap',
                               return_value=snap_name):
            self.common._sync_check(array, device_id, extra_specs)
            mock_break.assert_called_with(
                array, target, device_id, snap_name, extra_specs, generation)
            mock_delete.assert_called_with(array, snap_name,
                                           device_id, restored=False,
                                           generation=generation)
        # Delete legacy temp snap
        mock_delete.reset_mock()
        snap_name2 = 'EMC_SMI_12345'
        sessions = [{'source_vol': device_id,
                     'snap_name': snap_name2,
                     'target_vol_list': [], 'generation': 0}]
        with mock.patch.object(self.rest, 'find_snap_vx_sessions',
                               return_value=sessions):
            with mock.patch.object(self.rest, 'get_volume_snap',
                                   return_value=snap_name2):
                self.common._sync_check(array, device_id, extra_specs)
                mock_delete.assert_called_once_with(
                    array, snap_name2, device_id, restored=False, generation=0)

    @mock.patch.object(provision.PowerMaxProvision, 'delete_volume_snap')
    @mock.patch.object(provision.PowerMaxProvision,
                       'break_replication_relationship')
    def test_sync_check_not_temp_snap(self, mock_break, mock_delete):
        array = self.data.array
        device_id = self.data.device_id
        target = self.data.volume_details[1]['volumeId']
        extra_specs = self.data.extra_specs
        snap_name = 'OS-1'
        sessions = [{'source_vol': device_id,
                     'snap_name': snap_name, 'generation': 0,
                     'target_vol_list': [(target, "Copied")]}]
        with mock.patch.object(self.rest, 'find_snap_vx_sessions',
                               return_value=sessions):
            self.common._sync_check(array, device_id, extra_specs)
            mock_break.assert_called_with(
                array, target, device_id, snap_name, extra_specs, 0)
            mock_delete.assert_not_called()

    @mock.patch.object(provision.PowerMaxProvision,
                       'break_replication_relationship')
    def test_sync_check_no_sessions(self, mock_break):
        array = self.data.array
        device_id = self.data.device_id
        extra_specs = self.data.extra_specs
        with mock.patch.object(self.rest, 'find_snap_vx_sessions',
                               return_value=None):
            self.common._sync_check(array, device_id, extra_specs)
            mock_break.assert_not_called()

    @mock.patch.object(provision.PowerMaxProvision, 'delete_volume_snap')
    @mock.patch.object(provision.PowerMaxProvision,
                       'break_replication_relationship')
    def test_clone_check_cinder_snap(self, mock_break, mock_delete):
        array = self.data.array
        device_id = self.data.device_id
        target = self.data.volume_details[1]['volumeId']
        extra_specs = self.data.extra_specs
        snap_name = 'OS-1'
        sessions = [{'source_vol': device_id,
                     'snap_name': snap_name, 'generation': 0,
                     'target_vol_list': [(target, "Copied")]}]

        with mock.patch.object(self.rest, 'is_vol_in_rep_session',
                               return_value=(True, False, None)):
            with mock.patch.object(self.rest, 'find_snap_vx_sessions',
                                   return_value=sessions):
                self.common._clone_check(array, device_id, extra_specs)
                mock_delete.assert_not_called()

        mock_delete.reset_mock()
        with mock.patch.object(self.rest, 'find_snap_vx_sessions',
                               return_value=sessions):
            self.common._clone_check(array, device_id, extra_specs)
            mock_break.assert_called_with(
                array, target, device_id, snap_name, extra_specs, 0)

    @mock.patch.object(provision.PowerMaxProvision, 'delete_volume_snap')
    @mock.patch.object(provision.PowerMaxProvision,
                       'break_replication_relationship')
    def test_clone_check_temp_snap(self, mock_break, mock_delete):
        array = self.data.array
        device_id = self.data.device_id
        target = self.data.volume_details[1]['volumeId']
        extra_specs = self.data.extra_specs
        temp_snap_name = 'temp-' + device_id + '-' + 'snapshot_for_clone'
        sessions = [{'source_vol': device_id,
                     'snap_name': temp_snap_name, 'generation': 0,
                     'target_vol_list': [(target, "Copied")]}]

        with mock.patch.object(self.rest, 'find_snap_vx_sessions',
                               return_value=sessions):
            self.common._clone_check(array, device_id, extra_specs)
            mock_break.assert_called_with(
                array, target, device_id, temp_snap_name, extra_specs, 0)
            mock_delete.assert_not_called()

        sessions1 = [{'source_vol': device_id,
                      'snap_name': temp_snap_name, 'generation': 0,
                      'target_vol_list': [(target, "CopyInProg")]}]
        mock_delete.reset_mock()
        mock_break.reset_mock()
        with mock.patch.object(self.rest, 'is_vol_in_rep_session',
                               return_value=(False, True, None)):
            with mock.patch.object(self.rest, 'find_snap_vx_sessions',
                                   return_value=sessions1):
                self.common._clone_check(array, device_id, extra_specs)
                mock_break.assert_not_called()
                mock_delete.assert_not_called()

    @mock.patch.object(provision.PowerMaxProvision,
                       'break_replication_relationship')
    def test_clone_check_no_sessions(self, mock_break):
        array = self.data.array
        device_id = self.data.device_id
        extra_specs = self.data.extra_specs
        with mock.patch.object(self.rest, 'find_snap_vx_sessions',
                               return_value=None):
            self.common._clone_check(array, device_id, extra_specs)
            mock_break.assert_not_called()

    def test_manage_existing_success(self):
        external_ref = {u'source-name': u'00002'}
        provider_location = {'device_id': u'00002', 'array': u'000197800123'}
        ref_update = {'provider_location': six.text_type(provider_location)}
        with mock.patch.object(
                self.common, '_check_lun_valid_for_cinder_management',
                return_value=('vol1', 'test_sg')):
            model_update = self.common.manage_existing(
                self.data.test_volume, external_ref)
            self.assertEqual(ref_update, model_update)

    @mock.patch.object(
        rest.PowerMaxRest, 'get_masking_views_from_storage_group',
        return_value=None)
    @mock.patch.object(rest.PowerMaxRest, 'is_vol_in_rep_session',
                       return_value=(False, False, None))
    def test_check_lun_valid_for_cinder_management(self, mock_rep, mock_mv):
        external_ref = {u'source-name': u'00003'}
        vol, source_sg = self.common._check_lun_valid_for_cinder_management(
            self.data.array, self.data.device_id3,
            self.data.test_volume.id, external_ref)
        self.assertEqual(vol, '123')
        self.assertIsNone(source_sg)

    @mock.patch.object(
        rest.PowerMaxRest, 'get_masking_views_from_storage_group',
        return_value=None)
    @mock.patch.object(rest.PowerMaxRest, 'is_vol_in_rep_session',
                       return_value=(False, False, None))
    def test_check_lun_valid_for_cinder_management_multiple_sg_exception(
            self, mock_rep, mock_mv):
        external_ref = {u'source-name': u'00004'}
        self.assertRaises(
            exception.ManageExistingInvalidReference,
            self.common._check_lun_valid_for_cinder_management,
            self.data.array, self.data.device_id4,
            self.data.test_volume.id, external_ref)

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
            self, mock_rep, mock_sg, mock_mvs, mock_get_vol):
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

    @mock.patch.object(common.PowerMaxCommon,
                       '_remove_vol_and_cleanup_replication')
    def test_unmanage_success(self, mock_rm):
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

    @mock.patch.object(common.PowerMaxCommon, '_slo_workload_migration')
    def test_retype(self, mock_migrate):
        device_id = self.data.device_id
        volume_name = self.data.test_volume.name
        extra_specs = self.data.extra_specs_intervals_set
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

    @mock.patch.object(
        rest.PowerMaxRest, 'get_volume',
        return_value=tpd.PowerMaxData.volume_details_attached)
    @mock.patch.object(rest.PowerMaxRest, 'get_storage_group',
                       return_value=tpd.PowerMaxData.sg_details[1])
    @mock.patch.object(utils.PowerMaxUtils, 'get_child_sg_name',
                       return_value=('OS-Test-SG', '', '', ''))
    @mock.patch.object(rest.PowerMaxRest, 'is_child_sg_in_parent_sg',
                       return_value=True)
    @mock.patch.object(masking.PowerMaxMasking,
                       'move_volume_between_storage_groups')
    @mock.patch.object(rest.PowerMaxRest, 'is_volume_in_storagegroup',
                       return_value=True)
    def test_retype_inuse_volume_tgt_sg_exist(self, mck_vol_in_sg, mck_sg_move,
                                              mck_child_sg_in_sg,
                                              mck_get_sg_name,
                                              mck_get_sg, mck_get_vol):
        array = self.data.array
        srp = self.data.srp
        slo = self.data.slo
        workload = self.data.workload
        device_id = self.data.device_id
        volume = self.data.test_attached_volume
        rep_mode = 'Synchronous'
        src_extra_specs = self.data.extra_specs_migrate
        interval = src_extra_specs['interval']
        retries = src_extra_specs['retries']
        tgt_extra_specs = {
            'srp': srp, 'array': array, 'slo': slo, 'workload': workload,
            'interval': interval, 'retries': retries, 'rep_mode': rep_mode}

        success = self.common._retype_inuse_volume(
            array, srp, volume, device_id, src_extra_specs, slo, workload,
            tgt_extra_specs, False)[0]
        self.assertTrue(success)
        mck_sg_move.assert_called()
        mck_vol_in_sg.assert_called()

    @mock.patch.object(
        rest.PowerMaxRest, 'get_volume',
        return_value=tpd.PowerMaxData.volume_details_attached)
    @mock.patch.object(utils.PowerMaxUtils, 'get_child_sg_name',
                       return_value=('OS-Test-SG', '', '', ''))
    @mock.patch.object(provision.PowerMaxProvision, 'create_storage_group')
    @mock.patch.object(masking.PowerMaxMasking, 'add_child_sg_to_parent_sg')
    @mock.patch.object(rest.PowerMaxRest, 'is_child_sg_in_parent_sg',
                       return_value=True)
    @mock.patch.object(masking.PowerMaxMasking,
                       'move_volume_between_storage_groups')
    @mock.patch.object(rest.PowerMaxRest, 'is_volume_in_storagegroup',
                       return_value=True)
    def test_retype_inuse_volume_no_tgt_sg(self, mck_vol_in_sg, mck_move_vol,
                                           mck_sg_in_sg, mck_add_sg_to_sg,
                                           mck_create_sg, mck_get_csg_name,
                                           mck_get_vol):
        array = self.data.array
        srp = self.data.srp
        slo = self.data.slo
        workload = self.data.workload
        device_id = self.data.device_id
        volume = self.data.test_attached_volume
        rep_mode = 'Synchronous'
        src_extra_specs = self.data.extra_specs_migrate
        interval = src_extra_specs['interval']
        retries = src_extra_specs['retries']
        tgt_extra_specs = {
            'srp': srp, 'array': array, 'slo': slo, 'workload': workload,
            'interval': interval, 'retries': retries, 'rep_mode': rep_mode}

        with mock.patch.object(self.rest, 'get_storage_group',
                               side_effect=[self.data.sg_details[1], None,
                                            self.data.sg_details[1]]):
            success = self.common._retype_inuse_volume(
                array, srp, volume, device_id, src_extra_specs, slo, workload,
                tgt_extra_specs, False)[0]
            mck_create_sg.assert_called()
            mck_add_sg_to_sg.assert_called()
            self.assertTrue(success)

    @mock.patch.object(
        rest.PowerMaxRest, 'get_volume',
        return_value=tpd.PowerMaxData.volume_details_attached)
    @mock.patch.object(rest.PowerMaxRest, 'get_storage_group',
                       return_value=tpd.PowerMaxData.sg_details[1])
    @mock.patch.object(utils.PowerMaxUtils, 'get_child_sg_name',
                       return_value=('OS-Test-SG', '', '', ''))
    @mock.patch.object(rest.PowerMaxRest, 'is_child_sg_in_parent_sg',
                       return_value=False)
    @mock.patch.object(masking.PowerMaxMasking,
                       'move_volume_between_storage_groups')
    @mock.patch.object(rest.PowerMaxRest, 'is_volume_in_storagegroup',
                       return_value=False)
    def test_retype_inuse_volume_fail(self, mck_vol_in_sg, mck_sg_move,
                                      mck_child_sg_in_sg, mck_get_sg_name,
                                      mck_get_sg, mck_get_vol):
        array = self.data.array
        srp = self.data.srp
        slo = self.data.slo
        workload = self.data.workload
        device_id = self.data.device_id
        volume = self.data.test_attached_volume
        rep_mode = 'Synchronous'
        src_extra_specs = self.data.extra_specs_migrate
        interval = src_extra_specs['interval']
        retries = src_extra_specs['retries']
        tgt_extra_specs = {
            'srp': srp, 'array': array, 'slo': slo, 'workload': workload,
            'interval': interval, 'retries': retries, 'rep_mode': rep_mode}

        success = self.common._retype_inuse_volume(
            array, srp, volume, device_id, src_extra_specs, slo, workload,
            tgt_extra_specs, False)[0]
        self.assertFalse(success)
        mck_vol_in_sg.assert_not_called()
        mck_sg_move.assert_not_called()

    @mock.patch.object(
        rest.PowerMaxRest, 'get_volume',
        return_value=tpd.PowerMaxData.volume_details_attached)
    @mock.patch.object(rest.PowerMaxRest, 'get_storage_group',
                       return_value=tpd.PowerMaxData.sg_details[1])
    @mock.patch.object(utils.PowerMaxUtils, 'get_volume_attached_hostname',
                       return_value=None)
    def test_retype_inuse_volume_fail_no_attached_host(self, mck_get_hostname,
                                                       mck_get_sg,
                                                       mck_get_vol):
        array = self.data.array
        srp = self.data.srp
        slo = self.data.slo
        workload = self.data.workload
        device_id = self.data.device_id
        volume = self.data.test_attached_volume
        rep_mode = 'Synchronous'
        src_extra_specs = self.data.extra_specs_migrate
        interval = src_extra_specs['interval']
        retries = src_extra_specs['retries']
        tgt_extra_specs = {
            'srp': srp, 'array': array, 'slo': slo, 'workload': workload,
            'interval': interval, 'retries': retries, 'rep_mode': rep_mode}

        success = self.common._retype_inuse_volume(
            array, srp, volume, device_id, src_extra_specs, slo, workload,
            tgt_extra_specs, False)[0]
        self.assertFalse(success)

    def test_slo_workload_migration_valid(self):
        device_id = self.data.device_id
        volume_name = self.data.test_volume.name
        extra_specs = self.data.extra_specs
        new_type = {'extra_specs': {}}
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
        new_type = {'extra_specs': {}}
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
        new_type = {'extra_specs': {}}
        migrate_status = self.common._slo_workload_migration(
            device_id, volume, host, volume_name, new_type, extra_specs)
        self.assertFalse(migrate_status)

    def test_slo_workload_migration_same_host_change_compression(self):
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

    @mock.patch.object(masking.PowerMaxMasking, 'remove_and_reset_members')
    def test_migrate_volume_success(self, mock_remove):
        with mock.patch.object(self.rest, 'is_volume_in_storagegroup',
                               return_value=True):
            device_id = self.data.device_id
            volume_name = self.data.test_volume.name
            extra_specs = self.data.extra_specs
            volume = self.data.test_volume
            new_type = {'extra_specs': {}}
            migrate_status = self.common._migrate_volume(
                self.data.array, volume, device_id, self.data.srp,
                self.data.slo, self.data.workload, volume_name,
                new_type, extra_specs)[0]
            self.assertTrue(migrate_status)

            target_extra_specs = {
                'array': self.data.array, 'interval': 3,
                'retries': 120, 'slo': self.data.slo,
                'srp': self.data.srp, 'workload': self.data.workload}
            mock_remove.assert_called_once_with(
                self.data.array, volume, device_id, volume_name,
                target_extra_specs, reset=True)
            mock_remove.reset_mock()

            with mock.patch.object(
                    self.rest, 'get_storage_groups_from_volume',
                    return_value=[]):
                migrate_status = self.common._migrate_volume(
                    self.data.array, volume, device_id, self.data.srp,
                    self.data.slo, self.data.workload, volume_name,
                    new_type, extra_specs)[0]
                self.assertTrue(migrate_status)
                mock_remove.assert_not_called()

    @mock.patch.object(common.PowerMaxCommon, 'cleanup_lun_replication')
    @mock.patch.object(common.PowerMaxCommon, '_retype_inuse_volume',
                       return_value=(True, 'Test'))
    @mock.patch.object(common.PowerMaxCommon,
                       'setup_inuse_volume_replication',
                       return_value=('Status', 'Data', 'Info'))
    @mock.patch.object(common.PowerMaxCommon, '_retype_remote_volume',
                       return_value=True)
    def test_migrate_in_use_volume(self, mck_remote_retype, mck_setup,
                                   mck_retype, mck_cleanup):
        # Array/Volume info
        array = self.data.array
        srp = self.data.srp
        slo = self.data.slo
        workload = self.data.workload
        device_id = self.data.device_id
        volume = self.data.test_attached_volume
        volume_name = self.data.test_attached_volume.name
        # Rep Config
        rep_mode = 'Synchronous'
        self.common.rep_config = {'mode': rep_mode}
        # Extra Specs
        new_type = {'extra_specs': {}}
        src_extra_specs = self.data.extra_specs_migrate
        interval = src_extra_specs['interval']
        retries = src_extra_specs['retries']
        tgt_extra_specs = {
            'srp': srp, 'array': array, 'slo': slo, 'workload': workload,
            'interval': interval, 'retries': retries, 'rep_mode': rep_mode}

        def _reset_mocks():
            mck_cleanup.reset_mock()
            mck_setup.reset_mock()
            mck_retype.reset_mock()
            mck_remote_retype.reset_mock()

        # Scenario 1: no_rep => no_rep
        with mock.patch.object(self.utils, 'is_replication_enabled',
                               side_effect=[False, False]):
            success = self.common._migrate_volume(
                array, volume, device_id, srp, slo, workload, volume_name,
                new_type, src_extra_specs)[0]
            mck_retype.assert_called_once_with(
                array, srp, volume, device_id, src_extra_specs, slo, workload,
                tgt_extra_specs, False)
            mck_cleanup.assert_not_called()
            mck_setup.assert_not_called()
            mck_remote_retype.assert_not_called()
            self.assertTrue(success)
            _reset_mocks()

        # Scenario 2: rep => no_rep
        with mock.patch.object(self.utils, 'is_replication_enabled',
                               side_effect=[True, False]):
            success = self.common._migrate_volume(
                array, volume, device_id, srp, slo, workload, volume_name,
                new_type, src_extra_specs)[0]
            mck_cleanup.assert_called_once_with(
                volume, volume_name, device_id, src_extra_specs)
            mck_retype.assert_called_once_with(
                array, srp, volume, device_id, src_extra_specs, slo, workload,
                tgt_extra_specs, False)
            mck_setup.assert_not_called()
            mck_remote_retype.assert_not_called()
            self.assertTrue(success)
            _reset_mocks()

        # Scenario 3: no_rep => rep
        with mock.patch.object(self.utils, 'is_replication_enabled',
                               side_effect=[False, True]):
            success = self.common._migrate_volume(
                array, volume, device_id, srp, slo, workload, volume_name,
                new_type, src_extra_specs)[0]
            mck_setup.assert_called_once_with(
                self.data.array, volume, device_id, src_extra_specs)
            mck_retype.assert_called_once_with(
                array, srp, volume, device_id, src_extra_specs, slo,
                workload, tgt_extra_specs, False)
            mck_cleanup.assert_not_called()
            mck_remote_retype.assert_not_called()
            self.assertTrue(success)
            _reset_mocks()

        # Scenario 4: rep => rep
        with mock.patch.object(self.utils, 'is_replication_enabled',
                               side_effect=[True, True]):
            success = self.common._migrate_volume(
                array, volume, device_id, srp, slo, workload, volume_name,
                new_type, src_extra_specs)[0]
            mck_retype.assert_called_once_with(
                array, srp, volume, device_id, src_extra_specs, slo, workload,
                tgt_extra_specs, False)
            mck_remote_retype.assert_called_once_with(
                array, volume, device_id, volume_name, rep_mode, True,
                tgt_extra_specs)
            mck_cleanup.assert_not_called()
            mck_setup.assert_not_called()
            self.assertTrue(success)

    @mock.patch.object(masking.PowerMaxMasking, 'remove_and_reset_members')
    def test_migrate_volume_failed_get_new_sg_failed(self, mock_remove):
        device_id = self.data.device_id
        volume_name = self.data.test_volume.name
        extra_specs = self.data.extra_specs
        new_type = {'extra_specs': {}}
        with mock.patch.object(
                self.masking, 'get_or_create_default_storage_group',
                side_effect=exception.VolumeBackendAPIException):
            migrate_status = self.common._migrate_volume(
                self.data.array, self.data.test_volume, device_id,
                self.data.srp, self.data.slo,
                self.data.workload, volume_name, new_type, extra_specs)
            self.assertFalse(migrate_status)

    def test_migrate_volume_failed_vol_not_added(self):
        device_id = self.data.device_id
        volume_name = self.data.test_volume.name
        extra_specs = self.data.extra_specs
        new_type = {'extra_specs': {}}
        with mock.patch.object(
                self.rest, 'is_volume_in_storagegroup',
                return_value=False):
            migrate_status = self.common._migrate_volume(
                self.data.array, self.data.test_volume, device_id,
                self.data.srp, self.data.slo,
                self.data.workload, volume_name, new_type, extra_specs)[0]
            self.assertFalse(migrate_status)

    def test_is_valid_for_storage_assisted_migration_true(self):
        device_id = self.data.device_id
        host = {'host': self.data.new_host}
        volume_name = self.data.test_volume.name
        ref_return = (True, 'Silver', 'OLTP')
        return_val = self.common._is_valid_for_storage_assisted_migration(
            device_id, host, self.data.array,
            self.data.srp, volume_name, False, False)
        self.assertEqual(ref_return, return_val)
        # No current sgs found
        with mock.patch.object(self.rest, 'get_storage_groups_from_volume',
                               return_value=None):
            return_val = self.common._is_valid_for_storage_assisted_migration(
                device_id, host, self.data.array, self.data.srp,
                volume_name, False, False)
            self.assertEqual(ref_return, return_val)
        host = {'host': 'HostX@Backend#Silver+SRP_1+000197800123'}
        ref_return = (True, 'Silver', 'NONE')
        return_val = self.common._is_valid_for_storage_assisted_migration(
            device_id, host, self.data.array,
            self.data.srp, volume_name, False, False)
        self.assertEqual(ref_return, return_val)

    def test_is_valid_for_storage_assisted_migration_false(self):
        device_id = self.data.device_id
        volume_name = self.data.test_volume.name
        ref_return = (False, None, None)
        # IndexError
        host = {'host': 'HostX@Backend#Silver+SRP_1+000197800123+dummy+data'}
        return_val = self.common._is_valid_for_storage_assisted_migration(
            device_id, host, self.data.array,
            self.data.srp, volume_name, False, False)
        self.assertEqual(ref_return, return_val)
        # Wrong array
        host2 = {'host': 'HostX@Backend#Silver+OLTP+SRP_1+00012345678'}
        return_val = self.common._is_valid_for_storage_assisted_migration(
            device_id, host2, self.data.array,
            self.data.srp, volume_name, False, False)
        self.assertEqual(ref_return, return_val)
        # Wrong srp
        host3 = {'host': 'HostX@Backend#Silver+OLTP+SRP_2+000197800123'}
        return_val = self.common._is_valid_for_storage_assisted_migration(
            device_id, host3, self.data.array,
            self.data.srp, volume_name, False, False)
        self.assertEqual(ref_return, return_val)
        # Already in correct sg
        host4 = {'host': self.data.fake_host}
        return_val = self.common._is_valid_for_storage_assisted_migration(
            device_id, host4, self.data.array,
            self.data.srp, volume_name, False, False)
        self.assertEqual(ref_return, return_val)

    def test_is_valid_for_storage_assisted_migration_next_gen(self):
        device_id = self.data.device_id
        host = {'host': self.data.new_host}
        volume_name = self.data.test_volume.name
        ref_return = (True, 'Silver', 'NONE')
        with mock.patch.object(self.rest, 'is_next_gen_array',
                               return_value=True):
            return_val = self.common._is_valid_for_storage_assisted_migration(
                device_id, host, self.data.array,
                self.data.srp, volume_name, False, False)
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
        model_update, __, __ = self.common.update_group(group,
                                                        add_vols,
                                                        remove_vols)
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

    @mock.patch.object(volume_utils, 'is_group_a_type', return_value=False)
    def test_delete_group(self, mock_check):
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

    @mock.patch.object(volume_utils, 'is_group_a_type', return_value=False)
    def test_delete_group_success(self, mock_check):
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

    def test_delete_group_already_deleted(self):
        group = self.data.test_group_failed
        ref_model_update = {'status': fields.GroupStatus.DELETED}
        volumes = []
        with mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                               return_value=True):
            model_update, __ = self.common._delete_group(group, volumes)
            self.assertEqual(ref_model_update, model_update)

    @mock.patch.object(volume_utils, 'is_group_a_type', return_value=False)
    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                       return_value=True)
    def test_delete_group_failed(self, mock_check, mock_type_check):
        group = self.data.test_group_1
        volumes = []
        ref_model_update = {'status': fields.GroupStatus.ERROR_DELETING}
        with mock.patch.object(
                self.rest, 'delete_storage_group',
                side_effect=exception.VolumeBackendAPIException):
            model_update, __ = self.common._delete_group(
                group, volumes)
        self.assertEqual(ref_model_update, model_update)

    @mock.patch.object(
        common.PowerMaxCommon, '_get_clone_vol_info',
        return_value=(tpd.PowerMaxData.device_id,
                      tpd.PowerMaxData.extra_specs, 1, 'tgt_vol'))
    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                       return_value=True)
    @mock.patch.object(volume_utils, 'is_group_a_type',
                       return_value=False)
    def test_create_group_from_src_success(self, mock_type,
                                           mock_cg_type, mock_info):
        ref_model_update = {'status': fields.GroupStatus.AVAILABLE}
        model_update, volumes_model_update = (
            self.common.create_group_from_src(
                None, self.data.test_group_1, [self.data.test_volume],
                self.data.test_group_snapshot_1, [], None, []))
        self.assertEqual(ref_model_update, model_update)

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
             'PortGroup': self.data.port_group_name_i})
        old_conf = tpfo.FakeConfiguration(None, 'CommonTests', 1, 1)
        configuration = tpfo.FakeConfiguration(
            None, 'CommonTests', 1, 1, san_ip='1.1.1.1', san_login='smc',
            vmax_array=self.data.array, vmax_srp='SRP_1', san_password='smc',
            san_api_port=8443, vmax_port_groups=[self.data.port_group_name_i])
        self.common.configuration = configuration
        kwargs_returned = self.common.get_attributes_from_cinder_config()
        self.assertEqual(kwargs_expected, kwargs_returned)
        self.common.configuration = old_conf
        kwargs = self.common.get_attributes_from_cinder_config()
        self.assertIsNone(kwargs)

    def test_get_attributes_from_cinder_config_with_port_override_old(self):
        kwargs_expected = (
            {'RestServerIp': '1.1.1.1', 'RestServerPort': 3448,
             'RestUserName': 'smc', 'RestPassword': 'smc', 'SSLVerify': False,
             'SerialNumber': self.data.array, 'srpName': 'SRP_1',
             'PortGroup': self.data.port_group_name_i})
        configuration = tpfo.FakeConfiguration(
            None, 'CommonTests', 1, 1, san_ip='1.1.1.1', san_login='smc',
            vmax_array=self.data.array, vmax_srp='SRP_1', san_password='smc',
            san_rest_port=3448, vmax_port_groups=[self.data.port_group_name_i])
        self.common.configuration = configuration
        kwargs_returned = self.common.get_attributes_from_cinder_config()
        self.assertEqual(kwargs_expected, kwargs_returned)

    def test_get_attributes_from_cinder_config_with_port_override_new(self):
        kwargs_expected = (
            {'RestServerIp': '1.1.1.1', 'RestServerPort': 3448,
             'RestUserName': 'smc', 'RestPassword': 'smc', 'SSLVerify': False,
             'SerialNumber': self.data.array, 'srpName': 'SRP_1',
             'PortGroup': self.data.port_group_name_i})
        configuration = tpfo.FakeConfiguration(
            None, 'CommonTests', 1, 1, san_ip='1.1.1.1', san_login='smc',
            vmax_array=self.data.array, vmax_srp='SRP_1', san_password='smc',
            san_api_port=3448, vmax_port_groups=[self.data.port_group_name_i])
        self.common.configuration = configuration
        kwargs_returned = self.common.get_attributes_from_cinder_config()
        self.assertEqual(kwargs_expected, kwargs_returned)

    def test_get_attributes_from_cinder_config_no_port(self):
        kwargs_expected = (
            {'RestServerIp': '1.1.1.1', 'RestServerPort': 8443,
             'RestUserName': 'smc', 'RestPassword': 'smc', 'SSLVerify': False,
             'SerialNumber': self.data.array, 'srpName': 'SRP_1',
             'PortGroup': self.data.port_group_name_i})
        configuration = tpfo.FakeConfiguration(
            None, 'CommonTests', 1, 1, san_ip='1.1.1.1', san_login='smc',
            vmax_array=self.data.array, vmax_srp='SRP_1', san_password='smc',
            vmax_port_groups=[self.data.port_group_name_i])
        self.common.configuration = configuration
        kwargs_returned = self.common.get_attributes_from_cinder_config()
        self.assertEqual(kwargs_expected, kwargs_returned)

    def test_get_ssl_attributes_from_cinder_config(self):
        conf = tpfo.FakeConfiguration(
            None, 'CommonTests', 1, 1, san_ip='1.1.1.1', san_login='smc',
            vmax_array=self.data.array, vmax_srp='SRP_1', san_password='smc',
            vmax_port_groups=[self.data.port_group_name_i],
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

    @mock.patch.object(rest.PowerMaxRest, 'get_volume_snap',
                       return_value={'snap_name': 'snap_name'})
    def test_manage_snapshot_success(self, mock_snap):
        snapshot = self.data.test_snapshot_manage
        existing_ref = {u'source-name': u'test_snap'}
        updates_response = self.common.manage_existing_snapshot(
            snapshot, existing_ref)

        prov_loc = {'source_id': self.data.device_id,
                    'snap_name': 'OS-%s' % existing_ref['source-name']}

        updates = {'display_name': 'my_snap',
                   'provider_location': six.text_type(prov_loc)}

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

    @mock.patch.object(common.PowerMaxCommon, '_sync_check')
    @mock.patch.object(rest.PowerMaxRest, 'modify_volume_snap')
    def test_unmanage_snapshot_no_sync_check(self, mock_mod, mock_sync):
        self.common.unmanage_snapshot(self.data.test_snapshot_manage)
        mock_mod.assert_called_once()
        mock_sync.assert_not_called()

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

    @mock.patch.object(provision.PowerMaxProvision, 'is_restore_complete',
                       return_value=True)
    @mock.patch.object(common.PowerMaxCommon, '_sync_check')
    @mock.patch.object(provision.PowerMaxProvision, 'revert_volume_snapshot')
    def test_revert_to_snapshot(self, mock_revert, mock_sync, mock_complete):
        volume = self.data.test_volume
        snapshot = self.data.test_snapshot
        array = self.data.array
        device_id = self.data.device_id
        snap_name = self.data.snap_location['snap_name']
        extra_specs = deepcopy(self.data.extra_specs_intervals_set)
        extra_specs['storagetype:portgroupname'] = (
            self.data.port_group_name_f)
        self.common.revert_to_snapshot(volume, snapshot)
        mock_revert.assert_called_once_with(
            array, device_id, snap_name, extra_specs)

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
                    'timestamp': mock.ANY},
                'source_reference': {'source-id': '00001'}}]
            self.assertEqual(snap_list, expected_response)

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
                    'generation': 0, 'secured': False, 'timeToLive': 'N/A',
                    'timestamp': mock.ANY},
                 'source_reference': {'source-id': '00003'}},
                {'reference': {'source-name': 'testSnap4'},
                 'safe_to_manage': True, 'size': 400, 'reason_not_safe': None,
                 'cinder_id': None, 'extra_info': {
                    'generation': 0, 'secured': False, 'timeToLive': 'N/A',
                    'timestamp': mock.ANY},
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
        self.common.configuration.vmax_service_level = 'Diamond'
        self.common.configuration.vmax_workload = 'DSS'
        response1 = self.common.get_attributes_from_cinder_config()
        self.assertEqual('Diamond', response1['ServiceLevel'])
        self.assertEqual('DSS', response1['Workload'])

        self.common.configuration.vmax_service_level = 'Diamond'
        self.common.configuration.vmax_workload = None
        response2 = self.common.get_attributes_from_cinder_config()
        self.assertEqual(self.common.configuration.vmax_service_level,
                         response2['ServiceLevel'])
        self.assertIsNone(response2['Workload'])

        expected_response = {
            'RestServerIp': '1.1.1.1', 'RestServerPort': 8443,
            'RestUserName': 'smc', 'RestPassword': 'smc', 'SSLVerify': False,
            'SerialNumber': '000197800123', 'srpName': 'SRP_1',
            'PortGroup': 'OS-fibre-PG'}

        self.common.configuration.vmax_service_level = None
        self.common.configuration.vmax_workload = 'DSS'
        response3 = self.common.get_attributes_from_cinder_config()
        self.assertEqual(expected_response, response3)

        self.common.configuration.vmax_service_level = None
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
            u4p_primary='10.10.10.10')
        self.common.configuration = configuration
        self.common._get_u4p_failover_info()
        self.assertTrue(self.rest.u4p_failover_enabled)
        self.assertIsNotNone(self.rest.u4p_failover_targets)

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
