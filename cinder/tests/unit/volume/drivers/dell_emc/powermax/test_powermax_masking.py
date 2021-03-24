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
from unittest import mock

from cinder import exception
from cinder.tests.unit import test
from cinder.tests.unit.volume.drivers.dell_emc.powermax import (
    powermax_data as tpd)
from cinder.tests.unit.volume.drivers.dell_emc.powermax import (
    powermax_fake_objects as tpfo)
from cinder.volume.drivers.dell_emc.powermax import common
from cinder.volume.drivers.dell_emc.powermax import masking
from cinder.volume.drivers.dell_emc.powermax import provision
from cinder.volume.drivers.dell_emc.powermax import rest
from cinder.volume.drivers.dell_emc.powermax import utils
from cinder.volume import volume_utils


class PowerMaxMaskingTest(test.TestCase):
    def setUp(self):
        self.data = tpd.PowerMaxData()
        super(PowerMaxMaskingTest, self).setUp()
        volume_utils.get_max_over_subscription_ratio = mock.Mock()
        self.replication_device = self.data.sync_rep_device
        configuration = tpfo.FakeConfiguration(
            None, 'MaskingTests', 1, 1, san_ip='1.1.1.1',
            san_login='smc', powermax_array=self.data.array,
            powermax_srp='SRP_1', san_password='smc', san_api_port=8443,
            powermax_port_groups=[self.data.port_group_name_f],
            replication_device=self.replication_device)
        self._gather_info = common.PowerMaxCommon._gather_info
        common.PowerMaxCommon._get_u4p_failover_info = mock.Mock()
        common.PowerMaxCommon._gather_info = mock.Mock()
        rest.PowerMaxRest._establish_rest_session = mock.Mock(
            return_value=tpfo.FakeRequestsSession())
        driver = common.PowerMaxCommon(
            'iSCSI', self.data.version, configuration=configuration)
        driver_fc = common.PowerMaxCommon(
            'FC', self.data.version, configuration=configuration)
        self.driver = driver
        self.driver_fc = driver_fc
        self.mask = self.driver.masking
        self.extra_specs = deepcopy(self.data.extra_specs)
        self.extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_i
        self.maskingviewdict = self.driver._populate_masking_dict(
            self.data.test_volume, self.data.connector, self.extra_specs)
        self.maskingviewdict['extra_specs'] = self.extra_specs
        self.maskingviewdict[utils.IS_MULTIATTACH] = False
        self.device_id = self.data.device_id
        self.volume_name = self.data.volume_details[0]['volume_identifier']

    def tearDown(self):
        super(PowerMaxMaskingTest, self).tearDown()
        common.PowerMaxCommon._gather_info = self._gather_info

    def test_sanity_port_group_check_none(self):
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.masking._sanity_port_group_check,
            None, self.data.array)

    @mock.patch.object(rest.PowerMaxRest, 'get_portgroup', return_value=None)
    def test_sanity_port_group_check_invalid_portgroup(self, mock_pg):
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.masking._sanity_port_group_check,
            None, self.data.array)

    @mock.patch.object(
        masking.PowerMaxMasking, '_check_director_and_port_status')
    @mock.patch.object(rest.PowerMaxRest, 'get_portgroup',
                       return_value=tpd.PowerMaxData.portgroup)
    def test_sanity_port_group_check(self, mock_pg, mock_check):
        self.driver.masking._sanity_port_group_check(
            self.data.port_group_name_f, self.data.array)

    @mock.patch.object(masking.PowerMaxMasking,
                       'get_or_create_masking_view_and_map_lun')
    def test_setup_masking_view(self, mock_get_or_create_mv):
        self.driver.masking.setup_masking_view(
            self.data.array, self.data.test_volume,
            self.maskingviewdict, self.extra_specs)
        mock_get_or_create_mv.assert_called_once()

    @mock.patch.object(masking.PowerMaxMasking,
                       '_check_adding_volume_to_storage_group')
    @mock.patch.object(masking.PowerMaxMasking, '_move_vol_from_default_sg',
                       return_value=None)
    @mock.patch.object(masking.PowerMaxMasking, '_get_or_create_masking_view',
                       side_effect=[None, 'Error in masking view retrieval',
                                    exception.VolumeBackendAPIException])
    @mock.patch.object(rest.PowerMaxRest, 'get_element_from_masking_view',
                       side_effect=[tpd.PowerMaxData.port_group_name_i,
                                    Exception('Exception')])
    def test_get_or_create_masking_view_and_map_lun(
            self, mock_masking_view_element, mock_masking, mock_move,
            mock_add_volume):
        rollback_dict = (
            self.driver.masking.get_or_create_masking_view_and_map_lun(
                self.data.array, self.data.test_volume,
                self.maskingviewdict['maskingview_name'],
                self.maskingviewdict, self.extra_specs))
        self.assertEqual(self.maskingviewdict, rollback_dict)
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.masking.get_or_create_masking_view_and_map_lun,
            self.data.array, self.data.test_volume,
            self.maskingviewdict['maskingview_name'],
            self.maskingviewdict, self.extra_specs)
        self.maskingviewdict['slo'] = None
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.masking.get_or_create_masking_view_and_map_lun,
            self.data.array, self.data.test_volume,
            self.maskingviewdict['maskingview_name'],
            self.maskingviewdict, self.extra_specs)

    @mock.patch.object(masking.PowerMaxMasking,
                       '_check_adding_volume_to_storage_group',
                       return_value=None)
    @mock.patch.object(
        rest.PowerMaxRest, 'move_volume_between_storage_groups',
        side_effect=[None, exception.VolumeBackendAPIException(data='')])
    @mock.patch.object(rest.PowerMaxRest, 'is_volume_in_storagegroup',
                       side_effect=[True, False, True])
    def test_move_vol_from_default_sg(
            self, mock_volume_in_sg, mock_move_volume, mock_add):
        msg = None
        for x in range(0, 2):
            msg = self.driver.masking._move_vol_from_default_sg(
                self.data.array, self.device_id, self.volume_name,
                self.data.defaultstoragegroup_name,
                self.data.storagegroup_name_i, self.extra_specs)
        mock_move_volume.assert_called_once()
        mock_add.assert_called_once()
        self.assertIsNone(msg)
        msg = self.driver.masking._move_vol_from_default_sg(
            self.data.array, self.device_id, self.volume_name,
            self.data.defaultstoragegroup_name,
            self.data.storagegroup_name_i, self.extra_specs)
        self.assertIsNotNone(msg)

    @mock.patch.object(rest.PowerMaxRest, 'modify_storage_group',
                       return_value=(200, tpfo.tpd.PowerMaxData.job_list[0]))
    @mock.patch.object(rest.PowerMaxRest, 'remove_child_sg_from_parent_sg')
    @mock.patch.object(masking.PowerMaxMasking, 'get_parent_sg_from_child',
                       side_effect=[None, tpd.PowerMaxData.parent_sg_f])
    @mock.patch.object(
        rest.PowerMaxRest, 'get_num_vols_in_sg', side_effect=[2, 1, 1])
    def test_move_volume_between_storage_groups(
            self, mock_num, mock_parent, mock_rm, mck_mod):
        for x in range(0, 3):
            self.driver.masking.move_volume_between_storage_groups(
                self.data.array, self.data.device_id,
                self.data.storagegroup_name_i, self.data.storagegroup_name_f,
                self.data.extra_specs)
        mock_rm.assert_called_once()
        ref_payload = (
            {"executionOption": "ASYNCHRONOUS",
             "editStorageGroupActionParam": {
                 "moveVolumeToStorageGroupParam": {
                     "volumeId": [self.data.device_id],
                     "storageGroupId": self.data.storagegroup_name_f,
                     "force": 'false'}}})
        mck_mod.assert_called_with(
            self.data.array, self.data.storagegroup_name_i, ref_payload)

    @mock.patch.object(rest.PowerMaxRest, 'remove_child_sg_from_parent_sg')
    @mock.patch.object(masking.PowerMaxMasking, 'get_parent_sg_from_child',
                       side_effect=[None, tpd.PowerMaxData.parent_sg_f])
    @mock.patch.object(rest.PowerMaxRest, 'move_volume_between_storage_groups')
    @mock.patch.object(
        rest.PowerMaxRest, 'get_num_vols_in_sg', return_value=1)
    def test_force_move_volume_between_storage_groups(
            self, mock_num, mock_move, mock_parent, mock_rm):

        self.driver.masking.move_volume_between_storage_groups(
            self.data.array, self.data.device_id,
            self.data.storagegroup_name_i, self.data.storagegroup_name_f,
            self.data.extra_specs, force=True)

        mock_move.assert_called_once_with(
            self.data.array, self.data.device_id,
            self.data.storagegroup_name_i, self.data.storagegroup_name_f,
            self.data.extra_specs, True)

    @mock.patch.object(
        masking.PowerMaxMasking, '_check_director_and_port_status')
    @mock.patch.object(rest.PowerMaxRest, 'get_masking_view',
                       side_effect=[tpd.PowerMaxData.maskingview,
                                    tpd.PowerMaxData.maskingview, None])
    @mock.patch.object(
        masking.PowerMaxMasking, '_validate_existing_masking_view',
        side_effect=[(tpd.PowerMaxData.maskingview[1]['storageGroupId'],
                      None), (None, 'Error Message')])
    @mock.patch.object(masking.PowerMaxMasking, '_create_new_masking_view',
                       return_value=None)
    def test_get_or_create_masking_view(self, mock_create_mv, mock_validate_mv,
                                        mock_get_mv, mock_check):
        for x in range(0, 3):
            self.driver.masking._get_or_create_masking_view(
                self.data.array, self.maskingviewdict,
                self.data.defaultstoragegroup_name, self.extra_specs)
        mock_create_mv.assert_called_once()

    @mock.patch.object(
        masking.PowerMaxMasking, '_get_or_create_initiator_group',
        side_effect=[(None, 'Initiator group error'), (None, None),
                     (None, None), (None, None), (None, None),
                     (None, None), (None, None), (None, None)])
    @mock.patch.object(
        masking.PowerMaxMasking, '_get_or_create_storage_group',
        side_effect=['Storage group not found', None,
                     'Storage group not found', 'Storage group not found',
                     None, None, None, None, None, None, None])
    @mock.patch.object(
        masking.PowerMaxMasking, '_move_vol_from_default_sg',
        side_effect=['Storage group error', None, 'Storage group error',
                     None])
    @mock.patch.object(
        masking.PowerMaxMasking, 'create_masking_view', return_value=None)
    def test_create_new_masking_view(
            self, mock_create_mv, mock_move, mock_create_SG, mock_create_IG):
        for x in range(0, 6):
            self.driver.masking._create_new_masking_view(
                self.data.array, self.maskingviewdict,
                self.maskingviewdict['maskingview_name'],
                self.data.defaultstoragegroup_name, self.extra_specs)
        mock_create_mv.assert_called_once()

    @mock.patch.object(
        masking.PowerMaxMasking, '_check_existing_storage_group',
        side_effect=[(tpd.PowerMaxData.storagegroup_name_i, None),
                     (tpd.PowerMaxData.storagegroup_name_i, None),
                     (None, 'Error Checking existing storage group')])
    @mock.patch.object(
        rest.PowerMaxRest, 'get_element_from_masking_view',
        return_value=tpd.PowerMaxData.port_group_name_i)
    @mock.patch.object(
        masking.PowerMaxMasking, '_check_port_group',
        side_effect=[(None, None), (None, 'Error checking pg')])
    @mock.patch.object(
        masking.PowerMaxMasking, '_check_existing_initiator_group',
        return_value=(tpd.PowerMaxData.initiatorgroup_name_i, None))
    def test_validate_existing_masking_view(
            self, mock_check_ig, mock_check_pg, mock_get_mv_element,
            mock_check_sg):
        for x in range(0, 3):
            self.driver.masking._validate_existing_masking_view(
                self.data.array, self.maskingviewdict,
                self.maskingviewdict['maskingview_name'],
                self.data.defaultstoragegroup_name, self.extra_specs)
        self.assertEqual(3, mock_check_sg.call_count)
        mock_get_mv_element.assert_called_with(
            self.data.array, self.maskingviewdict['maskingview_name'],
            portgroup=True)
        mock_check_ig.assert_called_once()

    @mock.patch.object(
        rest.PowerMaxRest, 'get_storage_group',
        side_effect=[tpd.PowerMaxData.storagegroup_name_i, None,
                     tpd.PowerMaxData.storagegroup_name_i])
    @mock.patch.object(
        provision.PowerMaxProvision, 'create_storage_group',
        side_effect=[tpd.PowerMaxData.storagegroup_name_i, None])
    def test_get_or_create_storage_group(self, mock_sg, mock_get_sg):
        for x in range(0, 2):
            self.driver.masking._get_or_create_storage_group(
                self.data.array, self.maskingviewdict,
                self.data.storagegroup_name_i, self.extra_specs)
        self.assertEqual(3, mock_get_sg.call_count)
        self.assertEqual(1, mock_sg.call_count)

    @mock.patch.object(
        rest.PowerMaxRest, 'get_storage_group',
        side_effect=[None, tpd.PowerMaxData.storagegroup_name_i])
    @mock.patch.object(
        provision.PowerMaxProvision, 'create_storage_group',
        side_effect=[tpd.PowerMaxData.storagegroup_name_i])
    def test_get_or_create_storage_group_is_parent(self, mock_sg, mock_get_sg):
        self.driver.masking._get_or_create_storage_group(
            self.data.array, self.maskingviewdict,
            self.data.storagegroup_name_i, self.extra_specs, True)
        self.assertEqual(2, mock_get_sg.call_count)
        self.assertEqual(1, mock_sg.call_count)

    @mock.patch.object(masking.PowerMaxMasking, '_move_vol_from_default_sg',
                       return_value=None)
    @mock.patch.object(masking.PowerMaxMasking, '_get_or_create_storage_group',
                       return_value=None)
    @mock.patch.object(rest.PowerMaxRest, 'get_element_from_masking_view',
                       return_value=tpd.PowerMaxData.parent_sg_i)
    @mock.patch.object(rest.PowerMaxRest, 'is_child_sg_in_parent_sg',
                       side_effect=[True, False])
    @mock.patch.object(masking.PowerMaxMasking,
                       '_check_add_child_sg_to_parent_sg', return_value=None)
    def test_check_existing_storage_group_success(
            self, mock_add_sg, mock_is_child, mock_get_mv_element,
            mock_create_sg, mock_move):
        masking_view_dict = deepcopy(self.data.masking_view_dict)
        masking_view_dict['extra_specs'] = self.data.extra_specs

        with mock.patch.object(
                self.driver.rest, 'get_storage_group',
                side_effect=[tpd.PowerMaxData.parent_sg_i,
                             tpd.PowerMaxData.storagegroup_name_i]):
            _, msg = (self.driver.masking._check_existing_storage_group(
                self.data.array, self.maskingviewdict['maskingview_name'],
                self.data.defaultstoragegroup_name, masking_view_dict,
                self.data.extra_specs))
            self.assertIsNone(msg)
            mock_create_sg.assert_not_called()

        with mock.patch.object(self.driver.rest, 'get_storage_group',
                               side_effect=[
                                   tpd.PowerMaxData.parent_sg_i, None]):
            _, msg = (self.driver.masking._check_existing_storage_group(
                self.data.array, self.maskingviewdict['maskingview_name'],
                self.data.defaultstoragegroup_name, masking_view_dict,
                self.data.extra_specs))
            self.assertIsNone(msg)
            mock_create_sg.assert_called_once_with(
                self.data.array, masking_view_dict,
                tpd.PowerMaxData.storagegroup_name_f,
                self.data.extra_specs)

    @mock.patch.object(masking.PowerMaxMasking, '_move_vol_from_default_sg',
                       side_effect=[None, 'Error Message'])
    @mock.patch.object(rest.PowerMaxRest, 'is_child_sg_in_parent_sg',
                       side_effect=[True, False, False])
    @mock.patch.object(rest.PowerMaxRest, 'get_element_from_masking_view',
                       return_value=tpd.PowerMaxData.parent_sg_i)
    @mock.patch.object(rest.PowerMaxRest, 'get_storage_group',
                       side_effect=[
                           None, tpd.PowerMaxData.parent_sg_i, None,
                           tpd.PowerMaxData.parent_sg_i, None,
                           tpd.PowerMaxData.parent_sg_i, None])
    def test_check_existing_storage_group_failed(
            self, mock_get_sg, mock_get_mv_element, mock_child, mock_move):
        masking_view_dict = deepcopy(self.data.masking_view_dict)
        masking_view_dict['extra_specs'] = self.data.extra_specs
        for x in range(0, 4):
            _, msg = (self.driver.masking._check_existing_storage_group(
                self.data.array, self.maskingviewdict['maskingview_name'],
                self.data.defaultstoragegroup_name, masking_view_dict,
                self.data.extra_specs))
            self.assertIsNotNone(msg)
        self.assertEqual(7, mock_get_sg.call_count)
        self.assertEqual(1, mock_move.call_count)

    @mock.patch.object(
        masking.PowerMaxMasking, '_check_director_and_port_status')
    @mock.patch.object(
        rest.PowerMaxRest, 'get_portgroup',
        side_effect=([tpd.PowerMaxData.port_group_name_i, None]))
    def test_check_port_group(
            self, mock_get_pg, mock_check):
        for x in range(0, 2):
            _, msg = self.driver.masking._check_port_group(
                self.data.array, self.maskingviewdict['maskingview_name'])
        self.assertIsNotNone(msg)
        self.assertEqual(2, mock_get_pg.call_count)

    @mock.patch.object(
        masking.PowerMaxMasking, '_find_initiator_group',
        side_effect=[tpd.PowerMaxData.initiatorgroup_name_i, None, None])
    @mock.patch.object(
        masking.PowerMaxMasking, '_create_initiator_group',
        side_effect=([tpd.PowerMaxData.initiatorgroup_name_i, None]))
    def test_get_or_create_initiator_group(self, mock_create_ig, mock_find_ig):
        self.driver.masking._get_or_create_initiator_group(
            self.data.array, self.data.initiatorgroup_name_i,
            self.data.connector, self.extra_specs)
        mock_create_ig.assert_not_called()
        found_init_group, msg = (
            self.driver.masking._get_or_create_initiator_group(
                self.data.array, self.data.initiatorgroup_name_i,
                self.data.connector, self.extra_specs))
        self.assertIsNone(msg)
        found_init_group, msg = (
            self.driver.masking._get_or_create_initiator_group(
                self.data.array, self.data.initiatorgroup_name_i,
                self.data.connector, self.extra_specs))
        self.assertIsNotNone(msg)

    def test_check_existing_initiator_group(self):
        with mock.patch.object(
                rest.PowerMaxRest, 'get_element_from_masking_view',
                return_value=tpd.PowerMaxData.initiatorgroup_name_f):
            ig_from_mv, msg = (
                self.driver.masking._check_existing_initiator_group(
                    self.data.array, self.maskingviewdict['maskingview_name'],
                    self.maskingviewdict, self.data.storagegroup_name_i,
                    self.data.port_group_name_i, self.extra_specs))
            self.assertEqual(self.data.initiatorgroup_name_f, ig_from_mv)

    def test_check_adding_volume_to_storage_group(self):
        with mock.patch.object(
                masking.PowerMaxMasking, '_create_initiator_group'):
            with mock.patch.object(
                rest.PowerMaxRest, 'is_volume_in_storagegroup',
                    side_effect=[True, False]):
                msg = (
                    self.driver.masking._check_adding_volume_to_storage_group(
                        self.data.array, self.device_id,
                        self.data.storagegroup_name_i,
                        self.maskingviewdict[utils.VOL_NAME],
                        self.maskingviewdict[utils.EXTRA_SPECS]))
                self.assertIsNone(msg)
                msg = (
                    self.driver.masking._check_adding_volume_to_storage_group(
                        self.data.array, self.device_id,
                        self.data.storagegroup_name_i,
                        self.maskingviewdict[utils.VOL_NAME],
                        self.maskingviewdict[utils.EXTRA_SPECS]))

    @mock.patch.object(rest.PowerMaxRest, 'add_vol_to_sg')
    def test_add_volume_to_storage_group(self, mock_add_volume):
        self.driver.masking.add_volume_to_storage_group(
            self.data.array, self.device_id, self.data.storagegroup_name_i,
            self.volume_name, self.extra_specs)
        mock_add_volume.assert_called_once()

    @mock.patch.object(rest.PowerMaxRest, 'remove_vol_from_sg')
    def test_remove_vol_from_storage_group(self, mock_remove_volume):
        with mock.patch.object(
                rest.PowerMaxRest, 'is_volume_in_storagegroup',
                side_effect=[False, True]):
            self.driver.masking.remove_vol_from_storage_group(
                self.data.array, self.device_id, self.data.storagegroup_name_i,
                self.volume_name, self.extra_specs)
            mock_remove_volume.assert_called_once()
            self.assertRaises(
                exception.VolumeBackendAPIException,
                self.driver.masking.remove_vol_from_storage_group,
                self.data.array, self.device_id, self.data.storagegroup_name_i,
                self.volume_name, self.extra_specs)

    def test_find_initiator_names(self):
        foundinitiatornames = self.driver.masking.find_initiator_names(
            self.data.connector)
        self.assertEqual(self.data.connector['initiator'],
                         foundinitiatornames[0])
        foundinitiatornames = self.driver_fc.masking.find_initiator_names(
            self.data.connector)
        self.assertEqual(self.data.connector['wwpns'][0],
                         foundinitiatornames[0])
        connector = {'ip': self.data.ip, 'initiator': None, 'host': 'HostX'}
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.masking.find_initiator_names, connector)
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver_fc.masking.find_initiator_names, connector)

    def test_find_initiator_group_found(self):
        with mock.patch.object(
                rest.PowerMaxRest, 'get_initiator_list',
                return_value=self.data.initiator_list[2]['initiatorId']):
            with mock.patch.object(
                    rest.PowerMaxRest, 'get_initiator_group_from_initiator',
                    return_value=self.data.initiator_list):
                found_init_group_nam = (
                    self.driver.masking._find_initiator_group(
                        self.data.array, ['FA-1D:4:123456789012345']))
                self.assertEqual(self.data.initiator_list,
                                 found_init_group_nam)

    def test_find_initiator_group_not_found(self):
        with mock.patch.object(
                rest.PowerMaxRest, 'get_initiator_list',
                return_value=self.data.initiator_list[2]['initiatorId']):
            with mock.patch.object(
                    rest.PowerMaxRest, 'get_initiator_group_from_initiator',
                    return_value=None):
                found_init_group_nam = (
                    self.driver.masking._find_initiator_group(
                        self.data.array, ['Error']))
                self.assertIsNone(found_init_group_nam)

    def test_create_masking_view(self):
        with mock.patch.object(rest.PowerMaxRest, 'create_masking_view',
                               side_effect=[None, Exception]):
            error_message = self.driver.masking.create_masking_view(
                self.data.array, self.maskingviewdict['maskingview_name'],
                self.data.storagegroup_name_i, self.data.port_group_name_i,
                self.data.initiatorgroup_name_i, self.extra_specs)
            self.assertIsNone(error_message)
            error_message = self.driver.masking.create_masking_view(
                self.data.array, self.maskingviewdict['maskingview_name'],
                self.data.storagegroup_name_i, self.data.port_group_name_i,
                self.data.initiatorgroup_name_i, self.extra_specs)
            self.assertIsNotNone(error_message)

    @mock.patch.object(masking.PowerMaxMasking,
                       '_return_volume_to_fast_managed_group')
    @mock.patch.object(masking.PowerMaxMasking, '_check_ig_rollback')
    def test_check_if_rollback_action_for_masking_required(
            self, mock_check_ig, mock_return):
        with mock.patch.object(rest.PowerMaxRest,
                               'get_storage_groups_from_volume',
                               side_effect=[
                                   exception.VolumeBackendAPIException,
                                   self.data.storagegroup_list,
                                   self.data.storagegroup_list, None,
                                   None, ]):
            self.assertRaises(
                exception.VolumeBackendAPIException,
                self.mask.check_if_rollback_action_for_masking_required,
                self.data.array, self.data.test_volume,
                self.device_id, self.maskingviewdict)
            with mock.patch.object(masking.PowerMaxMasking,
                                   'remove_and_reset_members'):
                self.maskingviewdict[
                    'default_sg_name'] = self.data.defaultstoragegroup_name
                self.mask.check_if_rollback_action_for_masking_required(
                    self.data.array, self.data.test_volume,
                    self.device_id, self.maskingviewdict)
                # Multiattach case
                self.mask.check_if_rollback_action_for_masking_required(
                    self.data.array, self.data.test_volume,
                    self.device_id, self.data.masking_view_dict_multiattach)
                mock_return.assert_called_once()

    @mock.patch.object(masking.PowerMaxMasking, '_recreate_masking_view')
    @mock.patch.object(rest.PowerMaxRest, 'get_initiator_group',
                       return_value=True)
    def test_verify_initiator_group_from_masking_view(
            self, mock_get_ig, mock_recreate_mv):
        mv_dict = deepcopy(self.maskingviewdict)
        mv_dict['initiator_check'] = True
        self.mask._verify_initiator_group_from_masking_view(
            self.data.array, mv_dict['maskingview_name'],
            mv_dict, self.data.initiatorgroup_name_i,
            self.data.storagegroup_name_i, self.data.port_group_name_i,
            self.extra_specs)
        mock_recreate_mv.assert_called()

    @mock.patch.object(masking.PowerMaxMasking, '_recreate_masking_view')
    @mock.patch.object(rest.PowerMaxRest, 'get_initiator_group',
                       return_value=True)
    @mock.patch.object(
        masking.PowerMaxMasking, '_find_initiator_group',
        return_value=tpd.PowerMaxData.initiatorgroup_name_i)
    def test_verify_initiator_group_from_masking_view_no_recreate(
            self, mock_find_ig, mock_get_ig, mock_recreate):
        mv_dict = deepcopy(self.maskingviewdict)
        mv_dict['initiator_check'] = False
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.mask._verify_initiator_group_from_masking_view,
            self.data.array, mv_dict['maskingview_name'],
            mv_dict, 'OS-Wrong-Host-I-IG',
            self.data.storagegroup_name_i, self.data.port_group_name_i,
            self.extra_specs)
        mock_recreate.assert_not_called()

    @mock.patch.object(rest.PowerMaxRest, 'delete_initiator_group')
    @mock.patch.object(rest.PowerMaxRest, 'get_initiator_group',
                       return_value=True)
    def test_recreate_masking_view(
            self, mock_get_ig, mock_delete_ig):

        ig_from_conn = self.data.initiatorgroup_name_i
        ig_from_mv = self.data.initiatorgroup_name_i
        ig_openstack = self.data.initiatorgroup_name_i

        self.mask._recreate_masking_view(
            self.data.array, ig_from_conn, ig_from_mv,
            ig_openstack, self.data.masking_view_name_i, [self.data.initiator],
            self.data.storagegroup_name_i, self.data.port_group_name_i,
            self.extra_specs)
        mock_delete_ig.assert_not_called()

    @mock.patch.object(rest.PowerMaxRest, 'delete_initiator_group')
    @mock.patch.object(rest.PowerMaxRest, 'get_initiator_group',
                       return_value=True)
    def test_recreate_masking_view_no_ig_from_connector(
            self, mock_get_ig, mock_delete_ig):

        ig_from_mv = self.data.initiatorgroup_name_i
        ig_openstack = self.data.initiatorgroup_name_i

        self.mask._recreate_masking_view(
            self.data.array, None, ig_from_mv,
            ig_openstack, self.data.masking_view_name_i, [self.data.initiator],
            self.data.storagegroup_name_i, self.data.port_group_name_i,
            self.extra_specs)
        mock_delete_ig.assert_called()

    @mock.patch.object(rest.PowerMaxRest, 'create_masking_view')
    @mock.patch.object(rest.PowerMaxRest, 'get_initiator_group',
                       return_value=True)
    def test_recreate_masking_view_wrong_host(
            self, mock_get_ig, mock_create_mv):

        ig_from_conn = 'OS-Wrong-Host-I-IG'
        ig_from_mv = self.data.initiatorgroup_name_i
        ig_openstack = self.data.initiatorgroup_name_i

        self.mask._recreate_masking_view(
            self.data.array, ig_from_conn, ig_from_mv,
            ig_openstack, self.data.masking_view_name_i, [self.data.initiator],
            self.data.storagegroup_name_i, self.data.port_group_name_i,
            self.extra_specs)
        mock_create_mv.assert_called()

    @mock.patch.object(rest.PowerMaxRest, 'delete_masking_view')
    @mock.patch.object(rest.PowerMaxRest, 'delete_initiator_group')
    @mock.patch.object(rest.PowerMaxRest, 'get_initiator_group',
                       return_value=True)
    @mock.patch.object(
        masking.PowerMaxMasking, '_find_initiator_group',
        return_value=tpd.PowerMaxData.initiatorgroup_name_i)
    def test_recreate_masking_view_delete_mv(
            self, mock_find_ig, mock_get_ig, mock_delete_ig, mock_delete_mv):

        mock_delete_mv.side_effect = [None, Exception]
        mv_dict = deepcopy(self.maskingviewdict)
        mv_dict['initiator_check'] = True
        verify_flag = self.mask._verify_initiator_group_from_masking_view(
            self.data.array, mv_dict['maskingview_name'],
            mv_dict, 'OS-Wrong-Host-I-IG',
            self.data.storagegroup_name_i, self.data.port_group_name_i,
            self.extra_specs)
        mock_delete_mv.assert_called()
        self.assertTrue(verify_flag)

    @mock.patch.object(rest.PowerMaxRest, 'create_initiator_group')
    def test_create_initiator_group(self, mock_create_ig):
        initiator_names = self.mask.find_initiator_names(self.data.connector)
        ret_init_group_name = self.mask._create_initiator_group(
            self.data.array, self.data.initiatorgroup_name_i, initiator_names,
            self.extra_specs)
        self.assertEqual(self.data.initiatorgroup_name_i, ret_init_group_name)

    @mock.patch.object(rest.PowerMaxRest, 'create_initiator_group',
                       side_effect=([exception.VolumeBackendAPIException(
                           masking.CREATE_IG_ERROR)]))
    def test_create_initiator_group_exception(self, mock_create_ig):
        initiator_names = self.mask.find_initiator_names(self.data.connector)
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.mask._create_initiator_group,
            self.data.array, self.data.initiatorgroup_name_i, initiator_names,
            self.extra_specs)

    @mock.patch.object(masking.PowerMaxMasking,
                       '_last_volume_delete_initiator_group')
    def test_check_ig_rollback(self, mock_last_volume):
        with mock.patch.object(
                masking.PowerMaxMasking, '_find_initiator_group',
                side_effect=[None, 'FAKE-I-IG',
                             self.data.initiatorgroup_name_i]):
            for x in range(0, 2):
                self.mask._check_ig_rollback(self.data.array,
                                             self.data.initiatorgroup_name_i,
                                             self.data.connector)
            mock_last_volume.assert_not_called()
            self.mask._check_ig_rollback(
                self.data.array, self.data.initiatorgroup_name_i,
                self.data.connector)
            mock_last_volume.assert_called()

    @mock.patch.object(masking.PowerMaxMasking, '_cleanup_deletion')
    def test_remove_and_reset_members(self, mock_cleanup):
        self.mask.remove_and_reset_members(
            self.data.array, self.device_id, self.data.test_volume,
            self.volume_name, self.extra_specs, reset=False)
        mock_cleanup.assert_called_once()

    @mock.patch.object(
        rest.PowerMaxRest, 'get_storage_groups_from_volume',
        side_effect=[[tpd.PowerMaxData.storagegroup_name_i],
                     [tpd.PowerMaxData.storagegroup_name_i],
                     [tpd.PowerMaxData.storagegroup_name_i,
                      tpd.PowerMaxData.storagegroup_name_f]])
    @mock.patch.object(masking.PowerMaxMasking, 'remove_volume_from_sg')
    @mock.patch.object(masking.PowerMaxMasking,
                       'add_volume_to_default_storage_group')
    def test_cleanup_deletion(self, mock_add, mock_remove_vol, mock_get_sg):
        self.mask._cleanup_deletion(
            self.data.array, self.data.test_volume, self.device_id,
            self.volume_name, self.extra_specs, None, True, None)
        mock_add.assert_not_called()
        self.mask._cleanup_deletion(
            self.data.array, self.data.test_volume, self.device_id,
            self.volume_name, self.extra_specs,
            self.data.connector, True, None)
        mock_add.assert_not_called()
        self.mask._cleanup_deletion(
            self.data.array, self.data.test_volume, self.device_id,
            self.volume_name, self.extra_specs, None, True, None)
        mock_add.assert_called_once_with(
            self.data.array, self.device_id,
            self.volume_name, self.extra_specs, volume=self.data.test_volume)

    @mock.patch.object(masking.PowerMaxMasking, '_last_vol_in_sg')
    @mock.patch.object(masking.PowerMaxMasking, '_multiple_vols_in_sg')
    def test_remove_volume_from_sg(self, mock_multiple_vols, mock_last_vol):
        with mock.patch.object(
                rest.PowerMaxRest, 'get_masking_views_from_storage_group',
                return_value=None):
            with mock.patch.object(
                    rest.PowerMaxRest, 'get_num_vols_in_sg',
                    side_effect=[2, 1]):
                self.mask.remove_volume_from_sg(
                    self.data.array, self.device_id, self.volume_name,
                    self.data.defaultstoragegroup_name, self.extra_specs)
                mock_last_vol.assert_not_called()
                self.mask.remove_volume_from_sg(
                    self.data.array, self.device_id, self.volume_name,
                    self.data.defaultstoragegroup_name, self.extra_specs)
                mock_last_vol.assert_called()

    @mock.patch.object(masking.PowerMaxMasking, '_last_vol_in_sg')
    @mock.patch.object(masking.PowerMaxMasking, '_multiple_vols_in_sg')
    def test_remove_volume_from_sg_2(self, mock_multiple_vols, mock_last_vol):
        with mock.patch.object(rest.PowerMaxRest, 'is_volume_in_storagegroup',
                               return_value=True):
            with mock.patch.object(
                    rest.PowerMaxRest, 'get_masking_views_from_storage_group',
                    return_value=[self.data.masking_view_name_i]):
                with mock.patch.object(
                    rest.PowerMaxRest, 'get_num_vols_in_sg',
                        side_effect=[2, 1]):
                    self.mask.remove_volume_from_sg(
                        self.data.array, self.device_id, self.volume_name,
                        self.data.storagegroup_name_i, self.extra_specs)
                    mock_last_vol.assert_not_called()
                    self.mask.remove_volume_from_sg(
                        self.data.array, self.device_id, self.volume_name,
                        self.data.storagegroup_name_i, self.extra_specs)
                    mock_last_vol.assert_called()

    @mock.patch.object(masking.PowerMaxMasking, '_last_vol_masking_views',
                       return_value=True)
    @mock.patch.object(masking.PowerMaxMasking, '_last_vol_no_masking_views',
                       return_value=True)
    def test_last_vol_in_sg(self, mock_no_mv, mock_mv):
        mv_list = [self.data.masking_view_name_i,
                   self.data.masking_view_name_f]
        with mock.patch.object(rest.PowerMaxRest,
                               'get_masking_views_from_storage_group',
                               side_effect=[mv_list, []]):
            for x in range(0, 2):
                self.mask._last_vol_in_sg(
                    self.data.array, self.device_id, self.volume_name,
                    self.data.storagegroup_name_i, self.extra_specs,
                    self.data.connector)
            self.assertEqual(1, mock_mv.call_count)
            self.assertEqual(1, mock_no_mv.call_count)

    @mock.patch.object(masking.PowerMaxMasking,
                       '_remove_last_vol_and_delete_sg')
    @mock.patch.object(masking.PowerMaxMasking,
                       '_delete_cascaded_storage_groups')
    @mock.patch.object(rest.PowerMaxRest, 'get_num_vols_in_sg',
                       side_effect=[1, 3])
    @mock.patch.object(rest.PowerMaxRest, 'delete_storage_group')
    @mock.patch.object(masking.PowerMaxMasking, 'get_parent_sg_from_child',
                       side_effect=[None, 'parent_sg_name', 'parent_sg_name'])
    def test_last_vol_no_masking_views(
            self, mock_get_parent, mock_delete, mock_num_vols,
            mock_delete_casc, mock_remove):
        for x in range(0, 3):
            self.mask._last_vol_no_masking_views(
                self.data.array, self.data.storagegroup_name_i,
                self.device_id, self.volume_name, self.extra_specs,
                False)
        self.assertEqual(1, mock_delete.call_count)
        self.assertEqual(1, mock_delete_casc.call_count)
        self.assertEqual(1, mock_remove.call_count)

    @mock.patch.object(masking.PowerMaxMasking,
                       '_remove_last_vol_and_delete_sg')
    @mock.patch.object(masking.PowerMaxMasking, '_delete_mv_ig_and_sg')
    @mock.patch.object(masking.PowerMaxMasking, '_get_num_vols_from_mv',
                       side_effect=[(1, 'parent_name'), (3, 'parent_name')])
    def test_last_vol_masking_views(
            self, mock_num_vols, mock_delete_all, mock_remove):
        for x in range(0, 2):
            self.mask._last_vol_masking_views(
                self.data.array, self.data.storagegroup_name_i,
                [self.data.masking_view_name_i], self.device_id,
                self.volume_name, self.extra_specs, self.data.connector,
                True)
        self.assertEqual(1, mock_delete_all.call_count)
        self.assertEqual(1, mock_remove.call_count)

    @mock.patch.object(masking.PowerMaxMasking,
                       'add_volume_to_default_storage_group')
    @mock.patch.object(rest.PowerMaxRest, 'get_num_vols_in_sg')
    @mock.patch.object(masking.PowerMaxMasking,
                       'remove_vol_from_storage_group')
    def test_multiple_vols_in_sg(self, mock_remove_vol, mock_get_volumes,
                                 mock_add):
        self.mask._multiple_vols_in_sg(
            self.data.array, self.device_id, self.data.storagegroup_name_i,
            self.volume_name, self.extra_specs, False)
        mock_remove_vol.assert_called_once()
        self.mask._multiple_vols_in_sg(
            self.data.array, self.device_id, self.data.storagegroup_name_i,
            self.volume_name, self.extra_specs, True)
        mock_add.assert_called_once()

    @mock.patch.object(rest.PowerMaxRest, 'get_element_from_masking_view')
    @mock.patch.object(masking.PowerMaxMasking,
                       '_last_volume_delete_masking_view')
    @mock.patch.object(masking.PowerMaxMasking,
                       '_last_volume_delete_initiator_group')
    @mock.patch.object(masking.PowerMaxMasking,
                       '_delete_cascaded_storage_groups')
    def test_delete_mv_ig_and_sg(self, mock_delete_sg, mock_delete_ig,
                                 mock_delete_mv, mock_get_element):
        self.mask._delete_mv_ig_and_sg(
            self.data.array, self.data.device_id,
            self.data.masking_view_name_i,
            self.data.storagegroup_name_i, self.data.parent_sg_i,
            self.data.connector, True, self.data.extra_specs)
        mock_delete_sg.assert_called_once()

    @mock.patch.object(rest.PowerMaxRest, 'delete_masking_view')
    def test_last_volume_delete_masking_view(self, mock_delete_mv):
        self.mask._last_volume_delete_masking_view(
            self.data.array, self.data.masking_view_name_i)
        mock_delete_mv.assert_called_once()

    @mock.patch.object(masking.PowerMaxMasking,
                       'return_volume_to_volume_group')
    @mock.patch.object(rest.PowerMaxRest, 'move_volume_between_storage_groups')
    @mock.patch.object(masking.PowerMaxMasking,
                       'get_or_create_default_storage_group')
    @mock.patch.object(masking.PowerMaxMasking, 'add_volume_to_storage_group')
    def test_add_volume_to_default_storage_group(
            self, mock_add_sg, mock_get_sg, mock_move, mock_return):
        self.mask.add_volume_to_default_storage_group(
            self.data.array, self.device_id, self.volume_name,
            self.extra_specs)
        mock_add_sg.assert_called_once()
        self.mask.add_volume_to_default_storage_group(
            self.data.array, self.device_id, self.volume_name,
            self.extra_specs, src_sg=self.data.storagegroup_name_i)
        mock_move.assert_called_once()
        vol_grp_member = deepcopy(self.data.test_volume)
        vol_grp_member.group_id = self.data.test_vol_grp_name_id_only
        self.mask.add_volume_to_default_storage_group(
            self.data.array, self.device_id, self.volume_name,
            self.extra_specs, volume=vol_grp_member)
        mock_return.assert_called_once()

    def test_add_volume_to_default_storage_group_next_gen(self):
        extra_specs = deepcopy(self.data.extra_specs)
        extra_specs.pop(utils.IS_RE, None)
        with mock.patch.object(rest.PowerMaxRest, 'is_next_gen_array',
                               return_value=True):
            with mock.patch.object(
                    self.mask,
                    'get_or_create_default_storage_group') as mock_get:
                self.mask.add_volume_to_default_storage_group(
                    self.data.array, self.device_id, self.volume_name,
                    extra_specs)
                mock_get.assert_called_once_with(
                    self.data.array, self.data.srp,
                    extra_specs[utils.SLO],
                    'NONE', extra_specs, False, False, None)

    @mock.patch.object(provision.PowerMaxProvision, 'create_storage_group')
    def test_get_or_create_default_storage_group(self, mock_create_sg):
        with mock.patch.object(
                rest.PowerMaxRest, 'get_vmax_default_storage_group',
                return_value=(None, self.data.storagegroup_name_i)):
            storage_group_name = self.mask.get_or_create_default_storage_group(
                self.data.array, self.data.srp, self.data.slo,
                self.data.workload, self.extra_specs)
            self.assertEqual(self.data.storagegroup_name_i, storage_group_name)
        with mock.patch.object(
                rest.PowerMaxRest, 'get_vmax_default_storage_group',
                return_value=('test_sg', self.data.storagegroup_name_i)):
            with mock.patch.object(
                rest.PowerMaxRest, 'get_masking_views_from_storage_group',
                    return_value=self.data.masking_view_name_i):
                self.assertRaises(
                    exception.VolumeBackendAPIException,
                    self.mask.get_or_create_default_storage_group,
                    self.data.array, self.data.srp, self.data.slo,
                    self.data.workload, self.extra_specs)

    @mock.patch.object(masking.PowerMaxMasking,
                       'add_volume_to_default_storage_group')
    @mock.patch.object(rest.PowerMaxRest, 'remove_child_sg_from_parent_sg')
    @mock.patch.object(rest.PowerMaxRest, 'delete_storage_group')
    @mock.patch.object(masking.PowerMaxMasking,
                       'remove_vol_from_storage_group')
    def test_remove_last_vol_and_delete_sg(self, mock_vol_sg,
                                           mock_delete_sg, mock_rm, mock_add):
        self.mask._remove_last_vol_and_delete_sg(
            self.data.array, self.device_id, self.volume_name,
            self.data.storagegroup_name_i, self.extra_specs)
        self.mask._remove_last_vol_and_delete_sg(
            self.data.array, self.device_id, self.volume_name,
            self.data.storagegroup_name_i, self.extra_specs,
            self.data.parent_sg_i, True)
        self.assertEqual(2, mock_delete_sg.call_count)
        self.assertEqual(1, mock_vol_sg.call_count)
        self.assertEqual(1, mock_rm.call_count)
        self.assertEqual(1, mock_add.call_count)

    @mock.patch.object(rest.PowerMaxRest, 'delete_initiator_group')
    def test_last_volume_delete_initiator_group(self, mock_delete_ig):
        self.mask._last_volume_delete_initiator_group(
            self.data.array, self.data.initiatorgroup_name_f, 'Wrong_Host')
        mock_delete_ig.assert_not_called()
        self.mask._last_volume_delete_initiator_group(
            self.data.array, self.data.initiatorgroup_name_f, None)
        mock_delete_ig.assert_not_called()
        mv_list = [self.data.masking_view_name_i,
                   self.data.masking_view_name_f]
        with mock.patch.object(
                rest.PowerMaxRest, 'get_masking_views_by_initiator_group',
                side_effect=[mv_list, []]):
            self.mask._last_volume_delete_initiator_group(
                self.data.array, self.data.initiatorgroup_name_i,
                self.data.connector['host'])
            mock_delete_ig.assert_not_called()
            self.mask._last_volume_delete_initiator_group(
                self.data.array, self.data.initiatorgroup_name_i,
                self.data.connector['host'])
            mock_delete_ig.assert_called_once()

    def test_populate_masking_dict_init_check_false(self):
        extra_specs = deepcopy(self.data.extra_specs)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        connector = self.data.connector
        with mock.patch.object(self.driver, '_get_initiator_check_flag',
                               return_value=False):
            masking_view_dict = self.driver._populate_masking_dict(
                self.data.test_volume, connector, extra_specs)
            self.assertFalse(masking_view_dict['initiator_check'])

    def test_populate_masking_dict_init_check_true(self):
        extra_specs = deepcopy(self.data.extra_specs)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        connector = self.data.connector
        with mock.patch.object(self.driver, '_get_initiator_check_flag',
                               return_value=True):
            masking_view_dict = self.driver._populate_masking_dict(
                self.data.test_volume, connector, extra_specs)
            self.assertTrue(masking_view_dict['initiator_check'])

    def test_check_existing_initiator_group_verify_true(self):
        mv_dict = deepcopy(self.data.masking_view_dict)
        mv_dict['initiator_check'] = True
        with mock.patch.object(
                rest.PowerMaxRest, 'get_element_from_masking_view',
                return_value=tpd.PowerMaxData.initiatorgroup_name_f):
            with mock.patch.object(
                    self.mask, '_verify_initiator_group_from_masking_view',
                    return_value=(
                        True,
                        self.data.initiatorgroup_name_f)) as mock_verify:
                self.mask._check_existing_initiator_group(
                    self.data.array, self.data.masking_view_name_f,
                    mv_dict, self.data.storagegroup_name_f,
                    self.data.port_group_name_f, self.data.extra_specs)
                mock_verify.assert_called_once_with(
                    self.data.array, self.data.masking_view_name_f,
                    mv_dict, self.data.initiatorgroup_name_f,
                    self.data.storagegroup_name_f,
                    self.data.port_group_name_f, self.data.extra_specs)

    @mock.patch.object(
        masking.PowerMaxMasking, 'add_child_sg_to_parent_sg',
        side_effect=[None, exception.VolumeBackendAPIException])
    @mock.patch.object(rest.PowerMaxRest, 'is_child_sg_in_parent_sg',
                       side_effect=[True, False, False])
    def test_check_add_child_sg_to_parent_sg(self, mock_is_child, mock_add):
        for x in range(0, 3):
            message = self.mask._check_add_child_sg_to_parent_sg(
                self.data.array, self.data.storagegroup_name_i,
                self.data.parent_sg_i, self.data.extra_specs)
        self.assertIsNotNone(message)

    @mock.patch.object(rest.PowerMaxRest, 'add_child_sg_to_parent_sg')
    @mock.patch.object(rest.PowerMaxRest, 'is_child_sg_in_parent_sg',
                       side_effect=[True, False])
    def test_add_child_sg_to_parent_sg(self, mock_is_child, mock_add):
        for x in range(0, 2):
            self.mask.add_child_sg_to_parent_sg(
                self.data.array, self.data.storagegroup_name_i,
                self.data.parent_sg_i, self.data.extra_specs)
        self.assertEqual(1, mock_add.call_count)

    def test_get_parent_sg_from_child(self):
        with mock.patch.object(self.driver.rest, 'get_storage_group',
                               side_effect=[None, self.data.sg_details[1]]):
            sg_name = self.mask.get_parent_sg_from_child(
                self.data.array, self.data.storagegroup_name_i)
            self.assertIsNone(sg_name)
            sg_name2 = self.mask.get_parent_sg_from_child(
                self.data.array, self.data.storagegroup_name_f)
            self.assertEqual(self.data.parent_sg_f, sg_name2)

    @mock.patch.object(rest.PowerMaxRest, 'get_element_from_masking_view',
                       return_value='parent_sg')
    @mock.patch.object(rest.PowerMaxRest, 'get_num_vols_in_sg',
                       return_value=2)
    def test_get_num_vols_from_mv(self, mock_num, mock_element):
        num_vols, sg = self.mask._get_num_vols_from_mv(
            self.data.array, self.data.masking_view_name_f)
        self.assertEqual(2, num_vols)

    @mock.patch.object(masking.PowerMaxMasking,
                       'add_volume_to_default_storage_group')
    @mock.patch.object(rest.PowerMaxRest, 'delete_storage_group')
    def test_delete_cascaded(self, mock_delete, mock_add):
        self.mask._delete_cascaded_storage_groups(
            self.data.array, self.data.masking_view_name_f,
            self.data.parent_sg_f, self.data.extra_specs,
            self.data.device_id, False)
        self.assertEqual(2, mock_delete.call_count)
        mock_add.assert_not_called()
        # Delete legacy masking view, parent sg = child sg
        mock_delete.reset_mock()
        self.mask._delete_cascaded_storage_groups(
            self.data.array, self.data.masking_view_name_f,
            self.data.masking_view_name_f, self.data.extra_specs,
            self.data.device_id, True)
        self.assertEqual(1, mock_delete.call_count)
        mock_add.assert_called_once()

    @mock.patch.object(masking.PowerMaxMasking,
                       'add_volumes_to_storage_group')
    def test_add_remote_vols_to_volume_group(self, mock_add):
        self.mask.add_remote_vols_to_volume_group(
            [self.data.test_volume], self.data.test_rep_group,
            self.data.rep_extra_specs)
        mock_add.assert_called_once()

    @mock.patch.object(masking.PowerMaxMasking,
                       'add_remote_vols_to_volume_group')
    @mock.patch.object(masking.PowerMaxMasking,
                       '_check_adding_volume_to_storage_group')
    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                       return_value=True)
    @mock.patch.object(volume_utils, 'is_group_a_type',
                       side_effect=[False, False, True, True])
    def test_return_volume_to_volume_group(self, mock_type, mock_cg,
                                           mock_check, mock_add):
        vol_grp_member = deepcopy(self.data.test_volume)
        vol_grp_member.group_id = self.data.test_vol_grp_name_id_only
        vol_grp_member.group = self.data.test_group
        for x in range(0, 2):
            self.mask.return_volume_to_volume_group(
                self.data.array, vol_grp_member, self.data.device_id,
                self.data.test_volume.name, self.data.extra_specs)
        mock_add.assert_called_once()

    @mock.patch.object(masking.PowerMaxMasking,
                       '_return_volume_to_fast_managed_group')
    def test_pre_multiattach(self, mock_return):
        mv_dict = self.mask.pre_multiattach(
            self.data.array, self.data.device_id,
            self.data.masking_view_dict_multiattach,
            self.data.extra_specs)
        mock_return.assert_not_called()
        self.assertEqual(self.data.storagegroup_name_f,
                         mv_dict[utils.FAST_SG])
        with mock.patch.object(
                self.mask, 'move_volume_between_storage_groups',
                side_effect=exception.CinderException):
            self.assertRaises(
                exception.VolumeBackendAPIException,
                self.mask.pre_multiattach, self.data.array,
                self.data.device_id, self.data.masking_view_dict_multiattach,
                self.data.extra_specs)
            mock_return.assert_called_once()

    def test_pre_multiattach_next_gen(self):
        with mock.patch.object(utils.PowerMaxUtils, 'truncate_string',
                               return_value='DiamondDSS'):
            self.mask.pre_multiattach(
                self.data.array, self.data.device_id,
                self.data.masking_view_dict_multiattach,
                self.data.extra_specs)
            utils.PowerMaxUtils.truncate_string.assert_called_once_with(
                'DiamondDSS', 10)

    @mock.patch.object(masking.PowerMaxMasking,
                       '_clean_up_child_storage_group')
    @mock.patch.object(masking.PowerMaxMasking,
                       'move_volume_between_storage_groups')
    @mock.patch.object(masking.PowerMaxMasking,
                       '_return_volume_to_fast_managed_group')
    def test_pre_multiattach_pool_none_workload(self, mock_return, mck_move,
                                                mck_clean):
        with mock.patch.object(utils.PowerMaxUtils, 'truncate_string',
                               return_value='OptimdNONE'):
            self.mask.pre_multiattach(
                self.data.array, self.data.device_id,
                self.data.masking_view_dict_multiattach,
                self.data.extra_specs_optimized)
            utils.PowerMaxUtils.truncate_string.assert_called_once_with(
                'OptimizedNONE', 10)

    @mock.patch.object(
        rest.PowerMaxRest, 'get_storage_group_list',
        side_effect=[
            {'storageGroupId': [tpd.PowerMaxData.no_slo_sg_name]}, {}])
    @mock.patch.object(masking.PowerMaxMasking,
                       '_return_volume_to_fast_managed_group')
    def test_check_return_volume_to_fast_managed_group(
            self, mock_return, mock_sg):
        for x in range(0, 2):
            self.mask.return_volume_to_fast_managed_group(
                self.data.array, self.data.device_id,
                self.data.extra_specs)
        no_slo_specs = deepcopy(self.data.extra_specs)
        no_slo_specs[utils.SLO] = None
        self.mask.return_volume_to_fast_managed_group(
            self.data.array, self.data.device_id, no_slo_specs)
        mock_return.assert_called_once()

    @mock.patch.object(masking.PowerMaxMasking, '_move_vol_from_default_sg')
    @mock.patch.object(masking.PowerMaxMasking,
                       '_clean_up_child_storage_group')
    @mock.patch.object(masking.PowerMaxMasking, 'add_child_sg_to_parent_sg')
    @mock.patch.object(masking.PowerMaxMasking, '_get_or_create_storage_group')
    @mock.patch.object(
        rest.PowerMaxRest, 'get_storage_groups_from_volume',
        side_effect=[[tpd.PowerMaxData.no_slo_sg_name],
                     [tpd.PowerMaxData.storagegroup_name_f]])
    def test_return_volume_to_fast_managed_group(
            self, mock_sg, mock_get, mock_add, mock_clean, mock_move):
        for x in range(0, 2):
            self.mask._return_volume_to_fast_managed_group(
                self.data.array, self.data.device_id,
                self.data.parent_sg_f, self.data.storagegroup_name_f,
                self.data.no_slo_sg_name, self.data.extra_specs)
        mock_get.assert_called_once()
        mock_clean.assert_called_once()

    @mock.patch.object(rest.PowerMaxRest, 'delete_storage_group')
    @mock.patch.object(rest.PowerMaxRest, 'remove_child_sg_from_parent_sg')
    @mock.patch.object(rest.PowerMaxRest, 'is_child_sg_in_parent_sg',
                       side_effect=[False, True])
    @mock.patch.object(rest.PowerMaxRest, 'get_num_vols_in_sg',
                       side_effect=[2, 0, 0])
    @mock.patch.object(rest.PowerMaxRest, 'get_storage_group', side_effect=[
        None, 'child_sg', 'child_sg', 'child_sg'])
    def test_clean_up_child_storage_group(
            self, mock_sg, mock_num, mock_child, mock_rm, mock_del):
        # Storage group not found
        self.mask._clean_up_child_storage_group(
            self.data.array, self.data.storagegroup_name_f,
            self.data.parent_sg_f, self.data.extra_specs)
        mock_num.assert_not_called()
        # Storage group not empty
        self.mask._clean_up_child_storage_group(
            self.data.array, self.data.storagegroup_name_f,
            self.data.parent_sg_f, self.data.extra_specs)
        mock_child.assert_not_called()
        # Storage group not child
        self.mask._clean_up_child_storage_group(
            self.data.array, self.data.storagegroup_name_f,
            self.data.parent_sg_f, self.data.extra_specs)
        mock_rm.assert_not_called()
        # Storage group is child, and empty
        self.mask._clean_up_child_storage_group(
            self.data.array, self.data.storagegroup_name_f,
            self.data.parent_sg_f, self.data.extra_specs)
        mock_rm.assert_called_once()
        self.assertEqual(2, mock_del.call_count)

    @mock.patch.object(utils.PowerMaxUtils, 'verify_tag_list')
    def test_add_tags_to_storage_group_disabled(self, mock_verify):
        self.mask._add_tags_to_storage_group(
            self.data.array, self.data.add_volume_sg_info_dict,
            self.data.extra_specs)
        mock_verify.assert_not_called()

    @mock.patch.object(utils.PowerMaxUtils, 'verify_tag_list')
    def test_add_tags_to_storage_group_enabled(self, mock_verify):
        self.mask._add_tags_to_storage_group(
            self.data.array, self.data.add_volume_sg_info_dict,
            self.data.extra_specs_tags)
        mock_verify.assert_called()

    @mock.patch.object(utils.PowerMaxUtils, 'get_new_tags')
    def test_add_tags_to_storage_group_existing_tags(self, mock_inter):
        self.mask._add_tags_to_storage_group(
            self.data.array, self.data.storage_group_with_tags,
            self.data.extra_specs_tags)
        mock_inter.assert_called()

    @mock.patch.object(rest.PowerMaxRest, 'add_storage_group_tag',
                       side_effect=[exception.VolumeBackendAPIException])
    def test_add_tags_to_storage_group_exception(self, mock_except):
        self.mask._add_tags_to_storage_group(
            self.data.array, self.data.add_volume_sg_info_dict,
            self.data.extra_specs_tags)
        mock_except.assert_called()

    @mock.patch.object(rest.PowerMaxRest,
                       'get_masking_views_from_storage_group',
                       return_value=[tpd.PowerMaxData.masking_view_name_f])
    def test_get_host_and_port_group_labels(self, mock_mv):
        host_label, port_group_label = (
            self.mask._get_host_and_port_group_labels(
                self.data.array, self.data.parent_sg_f))
        self.assertEqual('HostX', host_label)
        self.assertEqual('OS-fibre-PG', port_group_label)

    @mock.patch.object(rest.PowerMaxRest,
                       'get_masking_views_from_storage_group',
                       return_value=['OS-HostX699ea-I-p-name3b02c-MV'])
    def test_get_host_and_port_group_labels_complex(self, mock_mv):
        host_label, port_group_label = (
            self.mask._get_host_and_port_group_labels(
                self.data.array, self.data.parent_sg_f))
        self.assertEqual('HostX699ea', host_label)
        self.assertEqual('p-name3b02c', port_group_label)

    @mock.patch.object(rest.PowerMaxRest,
                       'get_masking_views_from_storage_group',
                       return_value=['OS-myhost-I-myportgroup-MV'])
    def test_get_host_and_port_group_labels_plain(self, mock_mv):
        host_label, port_group_label = (
            self.mask._get_host_and_port_group_labels(
                self.data.array, self.data.parent_sg_f))
        self.assertEqual('myhost', host_label)
        self.assertEqual('myportgroup', port_group_label)

    @mock.patch.object(rest.PowerMaxRest,
                       'get_masking_views_from_storage_group',
                       return_value=[
                           'OS-host-with-dash-I-portgroup-with-dashes-MV'])
    def test_get_host_and_port_group_labels_dashes(self, mock_mv):
        host_label, port_group_label = (
            self.mask._get_host_and_port_group_labels(
                self.data.array, self.data.parent_sg_f))
        self.assertEqual('host-with-dash', host_label)
        self.assertEqual('portgroup-with-dashes', port_group_label)

    @mock.patch.object(
        rest.PowerMaxRest, 'is_child_sg_in_parent_sg', return_value=False)
    @mock.patch.object(
        rest.PowerMaxRest, 'add_child_sg_to_parent_sg')
    @mock.patch.object(
        rest.PowerMaxRest, 'get_storage_group',
        side_effect=[None, tpd.PowerMaxData.sg_details[1],
                     tpd.PowerMaxData.sg_details[2]])
    @mock.patch.object(
        provision.PowerMaxProvision, 'create_storage_group')
    def test_check_child_storage_group_exists_false(
            self, mock_create, mock_get, mock_add, mock_check):
        self.mask._check_child_storage_group_exists(
            self.data.device_id, self.data.array,
            self.data.storagegroup_name_i, self.data.extra_specs,
            self.data.parent_sg_i)
        mock_create.assert_called_once()
        mock_add.assert_called_once()

    @mock.patch.object(
        rest.PowerMaxRest, 'is_child_sg_in_parent_sg', return_value=True)
    @mock.patch.object(
        rest.PowerMaxRest, 'add_child_sg_to_parent_sg')
    @mock.patch.object(
        rest.PowerMaxRest, 'get_storage_group',
        side_effect=[tpd.PowerMaxData.sg_details[1],
                     tpd.PowerMaxData.sg_details[3]])
    @mock.patch.object(
        provision.PowerMaxProvision, 'create_storage_group')
    def test_check_child_storage_group_exists_true(
            self, mock_create, mock_get, mock_add, mock_check):
        self.mask._check_child_storage_group_exists(
            self.data.device_id, self.data.array,
            self.data.storagegroup_name_i, self.data.extra_specs,
            self.data.parent_sg_i)
        mock_create.assert_not_called
        mock_add.assert_not_called()

    @mock.patch.object(rest.PowerMaxRest, 'get_port',
                       return_value=tpd.PowerMaxData.port_info)
    @mock.patch.object(rest.PowerMaxRest, 'get_port_ids',
                       return_value=['FA-1D:4'])
    def test_check_director_and_port_status(self, mock_port_ids, mock_port):
        self.mask._check_director_and_port_status(
            self.data.array, self.data.port_group_name_f)

    @mock.patch.object(rest.PowerMaxRest, 'get_port',
                       return_value=tpd.PowerMaxData.port_info_off)
    @mock.patch.object(rest.PowerMaxRest, 'get_port_ids',
                       return_value=['FA-1D:4'])
    def test_check_director_and_port_status_invalid_status(
            self, mock_port_ids, mock_port):
        exception_message = (
            r"The director status is Offline and the port status is OFF for "
            r"dir:port FA-1D:4.")

        with self.assertRaisesRegex(
                exception.VolumeBackendAPIException,
                exception_message):
            self.mask._check_director_and_port_status(
                self.data.array, self.data.port_group_name_f)

    @mock.patch.object(rest.PowerMaxRest, 'get_port',
                       return_value=tpd.PowerMaxData.port_info_no_status)
    @mock.patch.object(rest.PowerMaxRest, 'get_port_ids',
                       return_value=['FA-1D:4'])
    def test_check_director_and_port_status_no_status(
            self, mock_port_ids, mock_port):
        exception_message = (
            r"Unable to get the director or port status for dir:port "
            r"FA-1D:4.")

        with self.assertRaisesRegex(
                exception.VolumeBackendAPIException,
                exception_message):
            self.mask._check_director_and_port_status(
                self.data.array, self.data.port_group_name_f)

    @mock.patch.object(rest.PowerMaxRest, 'get_port',
                       return_value=tpd.PowerMaxData.port_info_no_details)
    @mock.patch.object(rest.PowerMaxRest, 'get_port_ids',
                       return_value=['FA-1D:4'])
    def test_check_director_and_port_status_no_details(
            self, mock_port_ids, mock_port):
        exception_message = (
            r"Unable to get port information for dir:port FA-1D:4.")

        with self.assertRaisesRegex(
                exception.VolumeBackendAPIException,
                exception_message):
            self.mask._check_director_and_port_status(
                self.data.array, self.data.port_group_name_f)
