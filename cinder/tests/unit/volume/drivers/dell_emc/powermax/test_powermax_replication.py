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
from cinder import objects
from cinder.objects import fields
from cinder.objects import group
from cinder import test
from cinder.tests.unit.volume.drivers.dell_emc.powermax import (
    powermax_data as tpd)
from cinder.tests.unit.volume.drivers.dell_emc.powermax import (
    powermax_fake_objects as tpfo)
from cinder.volume.drivers.dell_emc.powermax import common
from cinder.volume.drivers.dell_emc.powermax import fc
from cinder.volume.drivers.dell_emc.powermax import iscsi
from cinder.volume.drivers.dell_emc.powermax import masking
from cinder.volume.drivers.dell_emc.powermax import provision
from cinder.volume.drivers.dell_emc.powermax import rest
from cinder.volume.drivers.dell_emc.powermax import utils
from cinder.volume import utils as volume_utils


class PowerMaxReplicationTest(test.TestCase):
    def setUp(self):
        self.data = tpd.PowerMaxData()
        super(PowerMaxReplicationTest, self).setUp()
        self.replication_device = {
            'target_device_id': self.data.remote_array,
            'remote_port_group': self.data.port_group_name_f,
            'remote_pool': self.data.srp2,
            'rdf_group_label': self.data.rdf_group_name,
            'allow_extend': 'True'}
        volume_utils.get_max_over_subscription_ratio = mock.Mock()
        configuration = tpfo.FakeConfiguration(
            None, 'CommonReplicationTests', 1, 1, san_ip='1.1.1.1',
            san_login='smc', vmax_array=self.data.array, vmax_srp='SRP_1',
            san_password='smc', san_api_port=8443,
            vmax_port_groups=[self.data.port_group_name_f],
            replication_device=self.replication_device)
        rest.PowerMaxRest._establish_rest_session = mock.Mock(
            return_value=tpfo.FakeRequestsSession())
        driver = fc.PowerMaxFCDriver(configuration=configuration)
        iscsi_config = tpfo.FakeConfiguration(
            None, 'CommonReplicationTests', 1, 1, san_ip='1.1.1.1',
            san_login='smc', vmax_array=self.data.array, vmax_srp='SRP_1',
            san_password='smc', san_api_port=8443,
            vmax_port_groups=[self.data.port_group_name_i],
            replication_device=self.replication_device)
        iscsi_driver = iscsi.PowerMaxISCSIDriver(configuration=iscsi_config)
        self.iscsi_common = iscsi_driver.common
        self.driver = driver
        self.common = self.driver.common
        self.masking = self.common.masking
        self.provision = self.common.provision
        self.rest = self.common.rest
        self.utils = self.common.utils
        self.utils.get_volumetype_extra_specs = (
            mock.Mock(
                return_value=self.data.vol_type_extra_specs_rep_enabled))
        self.extra_specs = deepcopy(self.data.extra_specs_rep_enabled)
        self.extra_specs['retries'] = 1
        self.extra_specs['interval'] = 1
        self.extra_specs['rep_mode'] = 'Synchronous'
        self.async_rep_device = {
            'target_device_id': self.data.remote_array,
            'remote_port_group': self.data.port_group_name_f,
            'remote_pool': self.data.srp2,
            'rdf_group_label': self.data.rdf_group_name,
            'allow_extend': 'True', 'mode': 'async'}
        async_configuration = tpfo.FakeConfiguration(
            None, 'CommonReplicationTests', 1, 1, san_ip='1.1.1.1',
            san_login='smc', vmax_array=self.data.array, vmax_srp='SRP_1',
            san_password='smc', san_api_port=8443,
            vmax_port_groups=[self.data.port_group_name_f],
            replication_device=self.async_rep_device)
        self.async_driver = fc.PowerMaxFCDriver(
            configuration=async_configuration)
        self.metro_rep_device = {
            'target_device_id': self.data.remote_array,
            'remote_port_group': self.data.port_group_name_f,
            'remote_pool': self.data.srp2,
            'rdf_group_label': self.data.rdf_group_name,
            'allow_extend': 'True', 'mode': 'metro'}
        metro_configuration = tpfo.FakeConfiguration(
            None, 'CommonReplicationTests', 1, 1, san_ip='1.1.1.1',
            san_login='smc', vmax_array=self.data.array, vmax_srp='SRP_1',
            san_password='smc', san_api_port=8443,
            vmax_port_groups=[self.data.port_group_name_f],
            replication_device=self.metro_rep_device)
        self.metro_driver = fc.PowerMaxFCDriver(
            configuration=metro_configuration)

    def test_get_replication_info(self):
        self.common._get_replication_info()
        self.assertTrue(self.common.replication_enabled)

    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                       return_value=False)
    @mock.patch.object(objects.group.Group, 'get_by_id',
                       return_value=tpd.PowerMaxData.test_rep_group)
    @mock.patch.object(volume_utils, 'is_group_a_type', return_value=True)
    @mock.patch.object(utils.PowerMaxUtils, 'check_replication_matched',
                       return_value=True)
    @mock.patch.object(masking.PowerMaxMasking, 'add_volume_to_storage_group')
    @mock.patch.object(
        common.PowerMaxCommon, '_replicate_volume',
        return_value=({
            'replication_driver_data':
                tpd.PowerMaxData.test_volume.replication_driver_data}, {}))
    def test_create_replicated_volume(self, mock_rep, mock_add, mock_match,
                                      mock_check, mock_get, mock_cg):
        extra_specs = deepcopy(self.extra_specs)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        vol_identifier = self.utils.get_volume_element_name(
            self.data.test_volume.id)
        self.common.create_volume(self.data.test_volume)
        volume_dict = self.data.provider_location
        mock_rep.assert_called_once_with(
            self.data.test_volume, vol_identifier, volume_dict,
            extra_specs)
        # Add volume to replication group
        self.common.create_volume(self.data.test_volume_group_member)
        mock_add.assert_called_once()

    @mock.patch.object(
        common.PowerMaxCommon, '_replicate_volume',
        return_value=({
            'replication_driver_data':
                tpd.PowerMaxData.test_volume.replication_driver_data}, {}))
    @mock.patch.object(utils.PowerMaxUtils, 'is_replication_enabled',
                       return_value=True)
    @mock.patch.object(rest.PowerMaxRest, 'get_rdf_group_number',
                       side_effect=['4', None])
    def test_create_replicated_vol_side_effect(
            self, mock_rdf_no, mock_rep_enabled, mock_rep_vol):
        self.common.rep_config = self.utils.get_replication_config(
            [self.replication_device])
        ref_rep_data = {'array': six.text_type(self.data.remote_array),
                        'device_id': self.data.device_id2}
        ref_model_update = {
            'provider_location': six.text_type(
                self.data.test_volume.provider_location),
            'replication_driver_data': six.text_type(ref_rep_data)}
        model_update = self.common.create_volume(self.data.test_volume)
        self.assertEqual(ref_model_update, model_update)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common.create_volume,
                          self.data.test_volume)

    def test_create_cloned_replicated_volume(self):
        extra_specs = deepcopy(self.extra_specs)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        with mock.patch.object(self.common, '_replicate_volume',
                               return_value=({}, {})) as mock_rep:
            self.common.create_cloned_volume(
                self.data.test_clone_volume, self.data.test_volume)
            volume_dict = self.data.provider_location_clone
            mock_rep.assert_called_once_with(
                self.data.test_clone_volume,
                self.data.test_clone_volume.name, volume_dict, extra_specs)

    def test_create_replicated_volume_from_snap(self):
        extra_specs = deepcopy(self.extra_specs)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        with mock.patch.object(self.common, '_replicate_volume',
                               return_value=({}, {})) as mock_rep:
            self.common.create_volume_from_snapshot(
                self.data.test_clone_volume, self.data.test_snapshot)
            volume_dict = self.data.provider_location_snapshot
            mock_rep.assert_called_once_with(
                self.data.test_clone_volume,
                'snapshot-%s' % self.data.snapshot_id, volume_dict,
                extra_specs)

    def test_replicate_volume(self):
        volume_dict = self.data.provider_location
        rs_enabled = fields.ReplicationStatus.ENABLED
        with mock.patch.object(
                self.common, 'setup_volume_replication',
                return_value=(rs_enabled, {}, {})) as mock_setup:
            self.common._replicate_volume(
                self.data.test_volume, '1', volume_dict, self.extra_specs)
            mock_setup.assert_called_once_with(
                self.data.array, self.data.test_volume,
                self.data.device_id, self.extra_specs)

    def test_replicate_volume_exception(self):
        volume_dict = self.data.provider_location
        with mock.patch.object(
                self.common, 'setup_volume_replication',
                side_effect=exception.VolumeBackendAPIException(data='')):
            with mock.patch.object(
                    self.common, '_cleanup_replication_source') as mock_clean:
                self.assertRaises(
                    exception.VolumeBackendAPIException,
                    self.common._replicate_volume, self.data.test_volume,
                    '1', volume_dict, self.extra_specs)
                mock_clean.assert_called_once_with(
                    self.data.array, self.data.test_volume, '1',
                    volume_dict, self.extra_specs)

    @mock.patch.object(common.PowerMaxCommon, '_remove_members')
    @mock.patch.object(
        common.PowerMaxCommon, '_get_replication_extra_specs',
        return_value=tpd.PowerMaxData.rep_extra_specs2)
    @mock.patch.object(
        utils.PowerMaxUtils, 'is_volume_failed_over', return_value=True)
    def test_unmap_lun_volume_failed_over(self, mock_fo, mock_es, mock_rm):
        extra_specs = deepcopy(self.extra_specs)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        rep_config = self.utils.get_replication_config(
            [self.replication_device])
        self.common._unmap_lun(self.data.test_volume, self.data.connector)
        mock_es.assert_called_once_with(extra_specs, rep_config)

    @mock.patch.object(common.PowerMaxCommon, '_remove_members')
    @mock.patch.object(
        common.PowerMaxCommon, '_get_replication_extra_specs',
        return_value=tpd.PowerMaxData.rep_extra_specs)
    @mock.patch.object(
        utils.PowerMaxUtils, 'is_metro_device', return_value=True)
    def test_unmap_lun_metro(self, mock_md, mock_es, mock_rm):
        extra_specs = deepcopy(self.extra_specs)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        self.common._unmap_lun(self.data.test_volume, self.data.connector)
        self.assertEqual(2, mock_rm.call_count)

    @mock.patch.object(
        utils.PowerMaxUtils, 'is_volume_failed_over', return_value=True)
    def test_initialize_connection_vol_failed_over(self, mock_fo):
        extra_specs = deepcopy(self.extra_specs)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        rep_extra_specs = deepcopy(tpd.PowerMaxData.rep_extra_specs)
        rep_extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        rep_config = self.utils.get_replication_config(
            [self.replication_device])
        with mock.patch.object(self.common, '_get_replication_extra_specs',
                               return_value=rep_extra_specs) as mock_es:
            self.common.initialize_connection(
                self.data.test_volume, self.data.connector)
            mock_es.assert_called_once_with(extra_specs, rep_config)

    @mock.patch.object(utils.PowerMaxUtils, 'is_metro_device',
                       return_value=True)
    @mock.patch.object(rest.PowerMaxRest, 'get_array_model_info',
                       return_value=('VMAX250F', False))
    def test_initialize_connection_vol_metro(self, mock_model, mock_md):
        metro_connector = deepcopy(self.data.connector)
        metro_connector['multipath'] = True
        info_dict = self.common.initialize_connection(
            self.data.test_volume, metro_connector)
        ref_dict = {'array': self.data.array,
                    'device_id': self.data.device_id,
                    'hostlunid': 3,
                    'maskingview': self.data.masking_view_name_f,
                    'metro_hostlunid': 3}
        self.assertEqual(ref_dict, info_dict)

    @mock.patch.object(rest.PowerMaxRest, 'get_iscsi_ip_address_and_iqn',
                       return_value=([tpd.PowerMaxData.ip],
                                     tpd.PowerMaxData.initiator))
    @mock.patch.object(common.PowerMaxCommon, '_get_replication_extra_specs',
                       return_value=tpd.PowerMaxData.rep_extra_specs)
    @mock.patch.object(utils.PowerMaxUtils, 'is_metro_device',
                       return_value=True)
    def test_initialize_connection_vol_metro_iscsi(self, mock_md, mock_es,
                                                   mock_ip):
        metro_connector = deepcopy(self.data.connector)
        metro_connector['multipath'] = True
        info_dict = self.iscsi_common.initialize_connection(
            self.data.test_volume, metro_connector)
        ref_dict = {'array': self.data.array,
                    'device_id': self.data.device_id,
                    'hostlunid': 3,
                    'maskingview': self.data.masking_view_name_f,
                    'ip_and_iqn': [{'ip': self.data.ip,
                                    'iqn': self.data.initiator}],
                    'metro_hostlunid': 3,
                    'is_multipath': True,
                    'metro_ip_and_iqn': [{'ip': self.data.ip,
                                          'iqn': self.data.initiator}]}
        self.assertEqual(ref_dict, info_dict)

    @mock.patch.object(utils.PowerMaxUtils, 'is_metro_device',
                       return_value=True)
    def test_initialize_connection_no_multipath_iscsi(self, mock_md):
        info_dict = self.iscsi_common.initialize_connection(
            self.data.test_volume, self.data.connector)
        self.assertIsNone(info_dict)

    @mock.patch.object(
        masking.PowerMaxMasking, 'pre_multiattach',
        return_value=tpd.PowerMaxData.masking_view_dict_multiattach)
    def test_attach_metro_volume(self, mock_pre):
        rep_extra_specs = deepcopy(tpd.PowerMaxData.rep_extra_specs)
        rep_extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        hostlunid, remote_port_group = self.common._attach_metro_volume(
            self.data.test_volume, self.data.connector, False,
            self.data.extra_specs, rep_extra_specs)
        self.assertEqual(self.data.port_group_name_f, remote_port_group)
        # Multiattach case
        self.common._attach_metro_volume(
            self.data.test_volume, self.data.connector, True,
            self.data.extra_specs, rep_extra_specs)
        mock_pre.assert_called_once()

    @mock.patch.object(rest.PowerMaxRest, 'is_vol_in_rep_session',
                       return_value=(False, False, None))
    @mock.patch.object(common.PowerMaxCommon, 'extend_volume_is_replicated')
    @mock.patch.object(common.PowerMaxCommon, '_sync_check')
    @mock.patch.object(rest.PowerMaxRest, 'get_array_model_info',
                       return_value=('VMAX250F', False))
    def test_extend_volume_rep_enabled(self, mock_model, mock_sync,
                                       mock_ex_re, mock_is_re):
        extra_specs = deepcopy(self.extra_specs)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        volume_name = self.data.test_volume.name
        self.common.extend_volume(self.data.test_volume, '5')
        mock_ex_re.assert_called_once_with(
            self.data.array, self.data.test_volume,
            self.data.device_id, volume_name, '5', extra_specs)

    def test_set_config_file_get_extra_specs_rep_enabled(self):
        extra_specs, _ = self.common._set_config_file_and_get_extra_specs(
            self.data.test_volume)
        self.assertTrue(extra_specs['replication_enabled'])

    def test_populate_masking_dict_is_re(self):
        extra_specs = deepcopy(self.extra_specs)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        masking_dict = self.common._populate_masking_dict(
            self.data.test_volume, self.data.connector, extra_specs)
        self.assertTrue(masking_dict['replication_enabled'])
        self.assertEqual('OS-HostX-SRP_1-DiamondDSS-OS-fibre-PG-RE',
                         masking_dict[utils.SG_NAME])

    @mock.patch.object(common.PowerMaxCommon,
                       '_replicate_volume',
                       return_value=({}, {}))
    @mock.patch.object(rest.PowerMaxRest, 'get_array_model_info',
                       return_value=('VMAX250F', False))
    def test_manage_existing_is_replicated(self, mock_model, mock_rep):
        extra_specs = deepcopy(self.extra_specs)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        external_ref = {u'source-name': u'00002'}
        volume_name = self.utils.get_volume_element_name(
            self.data.test_volume.id)
        provider_location = {'device_id': u'00002', 'array': self.data.array}
        with mock.patch.object(
                self.common, '_check_lun_valid_for_cinder_management',
                return_value=(volume_name, 'test_sg')):
            self.common.manage_existing(
                self.data.test_volume, external_ref)
            mock_rep.assert_called_once_with(
                self.data.test_volume, volume_name, provider_location,
                extra_specs, delete_src=False)

    @mock.patch.object(masking.PowerMaxMasking, 'remove_and_reset_members')
    @mock.patch.object(rest.PowerMaxRest, 'get_array_model_info',
                       return_value=('VMAX250F', False))
    def test_setup_volume_replication(self, mock_model, mock_rm):
        rep_status, rep_data, __ = self.common.setup_volume_replication(
            self.data.array, self.data.test_volume, self.data.device_id,
            self.extra_specs)
        self.assertEqual(fields.ReplicationStatus.ENABLED, rep_status)
        self.assertEqual({'array': self.data.remote_array,
                          'device_id': self.data.device_id}, rep_data)

    @mock.patch.object(masking.PowerMaxMasking, 'remove_and_reset_members')
    @mock.patch.object(common.PowerMaxCommon, '_create_volume')
    @mock.patch.object(rest.PowerMaxRest, 'get_array_model_info',
                       return_value=('VMAX250F', False))
    def test_setup_volume_replication_target(
            self, mock_model, mock_create, mock_rm):
        rep_status, rep_data, __ = self.common.setup_volume_replication(
            self.data.array, self.data.test_volume, self.data.device_id,
            self.extra_specs, self.data.device_id2)
        self.assertEqual(fields.ReplicationStatus.ENABLED, rep_status)
        self.assertEqual({'array': self.data.remote_array,
                          'device_id': self.data.device_id2}, rep_data)
        mock_create.assert_not_called()

    @mock.patch.object(common.PowerMaxCommon, 'get_rdf_details',
                       return_value=(tpd.PowerMaxData.rdf_group_no,
                                     tpd.PowerMaxData.remote_array))
    @mock.patch.object(rest.PowerMaxRest, 'get_size_of_device_on_array',
                       return_value=2)
    @mock.patch.object(common.PowerMaxCommon, '_get_replication_extra_specs',
                       return_value=tpd.PowerMaxData.rep_extra_specs5)
    @mock.patch.object(common.PowerMaxCommon, '_create_volume',
                       return_value=tpd.PowerMaxData.provider_location)
    @mock.patch.object(common.PowerMaxCommon, '_sync_check')
    @mock.patch.object(rest.PowerMaxRest, 'create_rdf_device_pair',
                       return_value=tpd.PowerMaxData.rdf_group_details)
    def test_setup_inuse_volume_replication(self, mck_create_rdf_pair,
                                            mck_sync_chk, mck_create_vol,
                                            mck_rep_specs, mck_get_vol_size,
                                            mck_get_rdf_info):
        array = self.data.array
        device_id = self.data.device_id
        volume = self.data.test_attached_volume
        extra_specs = self.data.extra_specs_migrate
        self.rep_config = self.data.rep_extra_specs4
        rep_status, rep_data, __ = (
            self.common.setup_inuse_volume_replication(
                array, volume, device_id, extra_specs))
        self.assertEqual('enabled', rep_status)
        self.assertEqual(self.data.rdf_group_details, rep_data)

    @mock.patch.object(rest.PowerMaxRest, 'get_array_model_info',
                       return_value=('VMAX250F', False))
    @mock.patch.object(common.PowerMaxCommon, '_cleanup_remote_target')
    def test_cleanup_lun_replication_success(self, mock_clean, mock_model):
        rep_extra_specs = deepcopy(self.data.rep_extra_specs)
        rep_extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        rep_extra_specs['target_array_model'] = 'VMAX250F'
        self.common.cleanup_lun_replication(
            self.data.test_volume, '1', self.data.device_id,
            self.extra_specs)
        mock_clean.assert_called_once_with(
            self.data.array, self.data.test_volume,
            self.data.remote_array, self.data.device_id,
            self.data.device_id2, self.data.rdf_group_no, '1',
            rep_extra_specs)
        # Cleanup legacy replication
        self.common.cleanup_lun_replication(
            self.data.test_legacy_vol, '1', self.data.device_id,
            self.extra_specs)
        mock_clean.assert_called_once_with(
            self.data.array, self.data.test_volume,
            self.data.remote_array, self.data.device_id,
            self.data.device_id2, self.data.rdf_group_no, '1',
            rep_extra_specs)

    @mock.patch.object(rest.PowerMaxRest, 'get_array_model_info',
                       return_value=('VMAX250F', False))
    @mock.patch.object(common.PowerMaxCommon, '_cleanup_remote_target')
    def test_cleanup_lun_replication_no_target(self, mock_clean, mock_model):
        with mock.patch.object(self.common, 'get_remote_target_device',
                               return_value=(None, '', '', '', '')):
            self.common.cleanup_lun_replication(
                self.data.test_volume, '1', self.data.device_id,
                self.extra_specs)
            mock_clean.assert_not_called()

    @mock.patch.object(
        common.PowerMaxCommon, 'get_remote_target_device',
        return_value=(tpd.PowerMaxData.device_id2, '', '', '', ''))
    @mock.patch.object(common.PowerMaxCommon,
                       '_add_volume_to_async_rdf_managed_grp')
    def test_cleanup_lun_replication_exception(self, mock_add, mock_tgt):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common.cleanup_lun_replication,
                          self.data.test_volume, '1', self.data.device_id,
                          self.extra_specs)
        # is metro or async volume
        extra_specs = deepcopy(self.extra_specs)
        extra_specs[utils.REP_MODE] = utils.REP_METRO
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common.cleanup_lun_replication,
                          self.data.test_volume, '1', self.data.device_id,
                          extra_specs)
        mock_add.assert_called_once()

    @mock.patch.object(common.PowerMaxCommon, '_cleanup_metro_target')
    @mock.patch.object(masking.PowerMaxMasking,
                       'remove_vol_from_storage_group')
    @mock.patch.object(common.PowerMaxCommon, '_delete_from_srp')
    @mock.patch.object(provision.PowerMaxProvision, 'break_rdf_relationship')
    def test_cleanup_remote_target(self, mock_break, mock_del,
                                   mock_rm, mock_clean_metro):
        with mock.patch.object(self.rest, 'are_vols_rdf_paired',
                               return_value=(False, '', '')):
            self.common._cleanup_remote_target(
                self.data.array, self.data.test_volume,
                self.data.remote_array, self.data.device_id,
                self.data.device_id2, self.data.rdf_group_name,
                'vol1', self.data.rep_extra_specs)
            mock_break.assert_not_called()
        self.common._cleanup_remote_target(
            self.data.array, self.data.test_volume,
            self.data.remote_array, self.data.device_id,
            self.data.device_id2, self.data.rdf_group_name,
            'vol1', self.data.rep_extra_specs)
        mock_break.assert_called_once_with(
            self.data.array, self.data.device_id,
            self.data.device_id2, self.data.rdf_group_name,
            self.data.rep_extra_specs, 'Synchronized')
        # is metro volume
        with mock.patch.object(self.utils, 'is_metro_device',
                               return_value=True):
            self.common._cleanup_remote_target(
                self.data.array, self.data.test_volume,
                self.data.remote_array, self.data.device_id,
                self.data.device_id2, self.data.rdf_group_name,
                'vol1', self.data.rep_extra_specs)
            mock_clean_metro.assert_called_once()

    def test_cleanup_remote_target_exception(self):
        extra_specs = deepcopy(self.data.rep_extra_specs)
        extra_specs['mode'] = utils.REP_METRO
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.metro_driver.common._cleanup_remote_target,
                          self.data.array, self.data.test_volume,
                          self.data.remote_array,
                          self.data.device_id, self.data.device_id2,
                          self.data.rdf_group_name, 'vol1', extra_specs)

    @mock.patch.object(provision.PowerMaxProvision, 'enable_group_replication')
    @mock.patch.object(rest.PowerMaxRest, 'get_num_vols_in_sg',
                       side_effect=[2, 0])
    def test_cleanup_metro_target(self, mock_vols, mock_enable):
        # allow delete is True
        specs = {'allow_del_metro': True}
        for x in range(0, 2):
            self.common._cleanup_metro_target(
                self.data.array, self.data.device_id, self.data.device_id2,
                self.data.rdf_group_no, specs)
            mock_enable.assert_called_once()
        # allow delete is False
        specs['allow_del_metro'] = False
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common._cleanup_metro_target,
                          self.data.array, self.data.device_id,
                          self.data.device_id2,
                          self.data.rdf_group_no, specs)

    @mock.patch.object(common.PowerMaxCommon,
                       '_remove_vol_and_cleanup_replication')
    @mock.patch.object(masking.PowerMaxMasking,
                       'remove_vol_from_storage_group')
    @mock.patch.object(common.PowerMaxCommon, '_delete_from_srp')
    def test_cleanup_replication_source(self, mock_del, mock_rm, mock_clean):
        self.common._cleanup_replication_source(
            self.data.array, self.data.test_volume, 'vol1',
            {'device_id': self.data.device_id}, self.extra_specs)
        mock_del.assert_called_once_with(
            self.data.array, self.data.device_id, 'vol1', self.extra_specs)

    def test_get_rdf_details(self):
        rdf_group_no, remote_array = self.common.get_rdf_details(
            self.data.array)
        self.assertEqual(self.data.rdf_group_no, rdf_group_no)
        self.assertEqual(self.data.remote_array, remote_array)

    def test_get_rdf_details_exception(self):
        with mock.patch.object(self.rest, 'get_rdf_group_number',
                               return_value=None):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.common.get_rdf_details, self.data.array)

    def test_failover_host(self):
        volumes = [self.data.test_volume, self.data.test_clone_volume]
        with mock.patch.object(self.common, '_failover_replication',
                               return_value=(None, {})) as mock_fo:
            self.common.failover_host(volumes)
            mock_fo.assert_called_once()

    @mock.patch.object(common.PowerMaxCommon, 'failover_replication',
                       return_value=({}, {}))
    def test_failover_host_groups(self, mock_fg):
        volumes = [self.data.test_volume_group_member]
        group1 = self.data.test_group
        self.common.failover_host(volumes, None, [group1])
        mock_fg.assert_called_once()

    def test_get_remote_target_device(self):
        target_device1, _, _, _, _ = (
            self.common.get_remote_target_device(
                self.data.array, self.data.test_volume, self.data.device_id))
        self.assertEqual(self.data.device_id2, target_device1)
        target_device2, _, _, _, _ = (
            self.common.get_remote_target_device(
                self.data.array, self.data.test_clone_volume,
                self.data.device_id))
        self.assertIsNone(target_device2)
        with mock.patch.object(self.rest, 'are_vols_rdf_paired',
                               return_value=(False, '')):
            target_device3, _, _, _, _ = (
                self.common.get_remote_target_device(
                    self.data.array, self.data.test_volume,
                    self.data.device_id))
            self.assertIsNone(target_device3)
        with mock.patch.object(self.rest, 'get_volume',
                               return_value=None):
            target_device4, _, _, _, _ = (
                self.common.get_remote_target_device(
                    self.data.array, self.data.test_volume,
                    self.data.device_id))
            self.assertIsNone(target_device4)

    @mock.patch.object(rest.PowerMaxRest, 'get_array_model_info',
                       return_value=('PowerMax 2000', True))
    @mock.patch.object(common.PowerMaxCommon, 'setup_volume_replication')
    @mock.patch.object(provision.PowerMaxProvision, 'extend_volume')
    @mock.patch.object(provision.PowerMaxProvision, 'break_rdf_relationship')
    @mock.patch.object(masking.PowerMaxMasking, 'remove_and_reset_members')
    def test_extend_volume_is_replicated(self, mock_remove, mock_break,
                                         mock_extend, mock_setup, mock_model):
        self.common.extend_volume_is_replicated(
            self.data.array, self.data.test_volume, self.data.device_id,
            'vol1', '5', self.data.extra_specs_rep_enabled)
        self.assertEqual(2, mock_remove.call_count)
        self.assertEqual(2, mock_extend.call_count)
        mock_remove.reset_mock()
        mock_extend.reset_mock()
        with mock.patch.object(self.rest, 'is_next_gen_array',
                               return_value=True):
            self.common.extend_volume_is_replicated(
                self.data.array, self.data.test_volume, self.data.device_id,
                'vol1', '5', self.data.extra_specs_rep_enabled)
            mock_remove.assert_not_called()
            self.assertEqual(2, mock_extend.call_count)

    def test_extend_volume_is_replicated_exception(self):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common.extend_volume_is_replicated,
                          self.data.failed_resource, self.data.test_volume,
                          self.data.device_id, 'vol1', '1',
                          self.data.extra_specs_rep_enabled)
        with mock.patch.object(self.utils, 'is_metro_device',
                               return_value=True):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.common.extend_volume_is_replicated,
                              self.data.array, self.data.test_volume,
                              self.data.device_id, 'vol1', '1',
                              self.data.extra_specs_rep_enabled)

    @mock.patch.object(rest.PowerMaxRest, 'get_array_model_info',
                       return_value=('VMAX250F', False))
    @mock.patch.object(common.PowerMaxCommon,
                       'add_volume_to_replication_group')
    @mock.patch.object(masking.PowerMaxMasking, 'remove_and_reset_members')
    def test_enable_rdf(self, mock_remove, mock_add, mock_model):
        rep_config = self.utils.get_replication_config(
            [self.replication_device])
        self.common.enable_rdf(
            self.data.array, self.data.test_volume, self.data.device_id,
            self.data.rdf_group_no, rep_config, 'OS-1',
            self.data.remote_array, self.data.device_id2, self.extra_specs)
        self.assertEqual(2, mock_remove.call_count)
        self.assertEqual(2, mock_add.call_count)

    @mock.patch.object(rest.PowerMaxRest, 'get_array_model_info',
                       return_value=('VMAX250F', False))
    @mock.patch.object(masking.PowerMaxMasking,
                       'remove_vol_from_storage_group')
    @mock.patch.object(common.PowerMaxCommon, '_cleanup_remote_target')
    def test_enable_rdf_exception(self, mock_cleanup, mock_rm, mock_model):
        rep_config = self.utils.get_replication_config(
            [self.replication_device])
        self.assertRaises(
            exception.VolumeBackendAPIException, self.common.enable_rdf,
            self.data.array, self.data.test_volume, self.data.device_id,
            self.data.failed_resource, rep_config, 'OS-1',
            self.data.remote_array, self.data.device_id2, self.extra_specs)
        self.assertEqual(1, mock_cleanup.call_count)

    def test_add_volume_to_replication_group(self):
        sg_name = self.common.add_volume_to_replication_group(
            self.data.array, self.data.device_id, 'vol1',
            self.extra_specs)
        self.assertEqual(self.data.default_sg_re_enabled, sg_name)

    @mock.patch.object(masking.PowerMaxMasking,
                       'get_or_create_default_storage_group',
                       side_effect=exception.VolumeBackendAPIException)
    def test_add_volume_to_replication_group_exception(self, mock_get):
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.common.add_volume_to_replication_group,
            self.data.array, self.data.device_id, 'vol1',
            self.extra_specs)

    @mock.patch.object(rest.PowerMaxRest,
                       'get_array_model_info',
                       return_value=('VMAX250F', False))
    def test_get_replication_extra_specs(self, mock_model):
        rep_config = self.utils.get_replication_config(
            [self.replication_device])
        # Path one - disable compression
        extra_specs1 = deepcopy(self.extra_specs)
        extra_specs1[utils.DISABLECOMPRESSION] = 'true'
        ref_specs1 = deepcopy(self.data.rep_extra_specs5)
        rep_extra_specs1 = self.common._get_replication_extra_specs(
            extra_specs1, rep_config)
        self.assertEqual(ref_specs1, rep_extra_specs1)
        # Path two - disable compression, not all flash
        ref_specs2 = deepcopy(self.data.rep_extra_specs5)
        with mock.patch.object(self.rest, 'is_compression_capable',
                               return_value=False):
            rep_extra_specs2 = self.common._get_replication_extra_specs(
                extra_specs1, rep_config)
        self.assertEqual(ref_specs2, rep_extra_specs2)

    @mock.patch.object(rest.PowerMaxRest,
                       'get_array_model_info',
                       return_value=('PowerMax 2000', True))
    def test_get_replication_extra_specs_powermax(self, mock_model):
        rep_config = self.utils.get_replication_config(
            [self.replication_device])
        rep_specs = deepcopy(self.data.rep_extra_specs2)
        extra_specs = deepcopy(self.extra_specs)

        # SLO not valid, both SLO and Workload set to NONE
        rep_specs['slo'] = None
        rep_specs['workload'] = None
        rep_specs['target_array_model'] = 'PowerMax 2000'
        with mock.patch.object(self.provision, 'verify_slo_workload',
                               return_value=(False, False)):
            rep_extra_specs = self.common._get_replication_extra_specs(
                extra_specs, rep_config)
            self.assertEqual(rep_specs, rep_extra_specs)
        # SL valid, workload invalid, only workload set to NONE
        rep_specs['slo'] = 'Diamond'
        rep_specs['workload'] = None
        rep_specs['target_array_model'] = 'PowerMax 2000'
        with mock.patch.object(self.provision, 'verify_slo_workload',
                               return_value=(True, False)):
            rep_extra_specs = self.common._get_replication_extra_specs(
                extra_specs, rep_config)
            self.assertEqual(rep_specs, rep_extra_specs)

    def test_get_secondary_stats(self):
        rep_config = self.utils.get_replication_config(
            [self.replication_device])
        array_map = self.common.get_attributes_from_cinder_config()
        finalarrayinfolist = self.common._get_slo_workload_combinations(
            array_map)
        array_info = finalarrayinfolist[0]
        ref_info = deepcopy(array_info)
        ref_info['SerialNumber'] = six.text_type(rep_config['array'])
        ref_info['srpName'] = rep_config['srp']
        secondary_info = self.common.get_secondary_stats_info(
            rep_config, array_info)
        self.assertEqual(ref_info, secondary_info)

    def test_replicate_group(self):
        volume_model_update = {
            'id': self.data.test_volume.id,
            'provider_location': self.data.test_volume.provider_location}
        vols_model_update = self.common._replicate_group(
            self.data.array, [volume_model_update],
            self.data.test_vol_grp_name, self.extra_specs)
        ref_rep_data = {'array': self.data.remote_array,
                        'device_id': self.data.device_id2}
        ref_vol_update = {
            'id': self.data.test_volume.id,
            'provider_location': self.data.test_volume.provider_location,
            'replication_driver_data': ref_rep_data,
            'replication_status': fields.ReplicationStatus.ENABLED}

        # Decode string representations of dicts into dicts, because
        # the string representations are randomly ordered and therefore
        # hard to compare.
        vols_model_update[0]['replication_driver_data'] = ast.literal_eval(
            vols_model_update[0]['replication_driver_data'])

        self.assertEqual(ref_vol_update, vols_model_update[0])

    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                       return_value=False)
    @mock.patch.object(volume_utils, 'is_group_a_type', return_value=True)
    def test_create_replicaton_group(self, mock_type, mock_cg_type):
        ref_model_update = {
            'status': fields.GroupStatus.AVAILABLE,
            'replication_status': fields.ReplicationStatus.ENABLED}
        model_update = self.common.create_group(None, self.data.test_group_1)
        self.assertEqual(ref_model_update, model_update)
        # Replication mode is async
        self.assertRaises(exception.InvalidInput,
                          self.async_driver.common.create_group,
                          None, self.data.test_group_1)

    def test_enable_replication(self):
        # Case 1: Group not replicated
        with mock.patch.object(volume_utils, 'is_group_a_type',
                               return_value=False):
            self.assertRaises(NotImplementedError,
                              self.common.enable_replication,
                              None, self.data.test_group,
                              [self.data.test_volume])
        with mock.patch.object(volume_utils, 'is_group_a_type',
                               return_value=True):
            # Case 2: Empty group
            model_update, __ = self.common.enable_replication(
                None, self.data.test_group, [])
            self.assertEqual({}, model_update)
            # Case 3: Successfully enabled
            model_update, __ = self.common.enable_replication(
                None, self.data.test_group, [self.data.test_volume])
            self.assertEqual(fields.ReplicationStatus.ENABLED,
                             model_update['replication_status'])
            # Case 4: Exception
            model_update, __ = self.common.enable_replication(
                None, self.data.test_group_failed, [self.data.test_volume])
            self.assertEqual(fields.ReplicationStatus.ERROR,
                             model_update['replication_status'])

    def test_disable_replication(self):
        # Case 1: Group not replicated
        with mock.patch.object(volume_utils, 'is_group_a_type',
                               return_value=False):
            self.assertRaises(NotImplementedError,
                              self.common.disable_replication,
                              None, self.data.test_group,
                              [self.data.test_volume])
        with mock.patch.object(volume_utils, 'is_group_a_type',
                               return_value=True):
            # Case 2: Empty group
            model_update, __ = self.common.disable_replication(
                None, self.data.test_group, [])
            self.assertEqual({}, model_update)
            # Case 3: Successfully disabled
            model_update, __ = self.common.disable_replication(
                None, self.data.test_group, [self.data.test_volume])
            self.assertEqual(fields.ReplicationStatus.DISABLED,
                             model_update['replication_status'])
            # Case 4: Exception
            model_update, __ = self.common.disable_replication(
                None, self.data.test_group_failed, [self.data.test_volume])
            self.assertEqual(fields.ReplicationStatus.ERROR,
                             model_update['replication_status'])

    def test_failover_replication(self):
        with mock.patch.object(volume_utils, 'is_group_a_type',
                               return_value=True):
            # Case 1: Empty group
            model_update, __ = self.common.failover_replication(
                None, self.data.test_group, [])
            self.assertEqual({}, model_update)
            # Case 2: Successfully failed over
            model_update, __ = self.common.failover_replication(
                None, self.data.test_group, [self.data.test_volume])
            self.assertEqual(fields.ReplicationStatus.FAILED_OVER,
                             model_update['replication_status'])
            # Case 3: Successfully failed back
            model_update, __ = self.common.failover_replication(
                None, self.data.test_group, [self.data.test_volume],
                secondary_backend_id='default')
            self.assertEqual(fields.ReplicationStatus.ENABLED,
                             model_update['replication_status'])
            # Case 4: Exception
            model_update, __ = self.common.failover_replication(
                None, self.data.test_group_failed, [self.data.test_volume])
            self.assertEqual(fields.ReplicationStatus.ERROR,
                             model_update['replication_status'])

    @mock.patch.object(provision.PowerMaxProvision, 'failover_group')
    def test_failover_replication_metro(self, mock_fo):
        volumes = [self.data.test_volume]
        _, vol_model_updates = self.common._failover_replication(
            volumes, group, None, host=True, is_metro=True)
        mock_fo.assert_not_called()

    @mock.patch.object(utils.PowerMaxUtils, 'get_volume_group_utils',
                       return_value=(tpd.PowerMaxData.array, {}))
    @mock.patch.object(common.PowerMaxCommon, '_cleanup_group_replication')
    @mock.patch.object(volume_utils, 'is_group_a_type', return_value=True)
    def test_delete_replication_group(self, mock_check,
                                      mock_cleanup, mock_utils):
        self.common._delete_group(self.data.test_rep_group, [])
        mock_cleanup.assert_called_once()

    @mock.patch.object(masking.PowerMaxMasking,
                       'remove_volumes_from_storage_group')
    @mock.patch.object(utils.PowerMaxUtils, 'check_rep_status_enabled')
    @mock.patch.object(common.PowerMaxCommon,
                       '_remove_remote_vols_from_volume_group')
    @mock.patch.object(masking.PowerMaxMasking,
                       'add_remote_vols_to_volume_group')
    @mock.patch.object(volume_utils, 'is_group_a_type', return_value=True)
    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                       return_value=True)
    def test_update_replicated_group(self, mock_cg_type, mock_type_check,
                                     mock_add, mock_remove, mock_check,
                                     mock_rm):
        add_vols = [self.data.test_volume]
        remove_vols = [self.data.test_clone_volume]
        self.common.update_group(
            self.data.test_group_1, add_vols, remove_vols)
        mock_add.assert_called_once()
        mock_remove.assert_called_once()

    @mock.patch.object(masking.PowerMaxMasking,
                       'remove_volumes_from_storage_group')
    def test_remove_remote_vols_from_volume_group(self, mock_rm):
        self.common._remove_remote_vols_from_volume_group(
            self.data.remote_array, [self.data.test_volume],
            self.data.test_rep_group, self.data.rep_extra_specs)
        mock_rm.assert_called_once()

    @mock.patch.object(masking.PowerMaxMasking, 'remove_and_reset_members')
    @mock.patch.object(masking.PowerMaxMasking,
                       'remove_volumes_from_storage_group')
    def test_cleanup_group_replication(self, mock_rm, mock_rm_reset):
        self.common._cleanup_group_replication(
            self.data.array, self.data.test_vol_grp_name,
            [self.data.device_id], self.extra_specs)
        mock_rm.assert_called_once()

    @mock.patch.object(masking.PowerMaxMasking, 'add_volume_to_storage_group')
    def test_add_volume_to_async_group(self, mock_add):
        extra_specs = deepcopy(self.extra_specs)
        extra_specs['rep_mode'] = utils.REP_ASYNC
        self.async_driver.common._add_volume_to_async_rdf_managed_grp(
            self.data.array, self.data.device_id, 'name',
            self.data.remote_array, self.data.device_id2, extra_specs)
        self.assertEqual(2, mock_add.call_count)

    def test_add_volume_to_async_group_exception(self):
        extra_specs = deepcopy(self.extra_specs)
        extra_specs['rep_mode'] = utils.REP_ASYNC
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.async_driver.common._add_volume_to_async_rdf_managed_grp,
            self.data.failed_resource, self.data.device_id, 'name',
            self.data.remote_array, self.data.device_id2, extra_specs)

    @mock.patch.object(rest.PowerMaxRest, 'get_array_model_info',
                       return_value=('VMAX250F', False))
    @mock.patch.object(common.PowerMaxCommon,
                       '_add_volume_to_async_rdf_managed_grp')
    @mock.patch.object(masking.PowerMaxMasking, 'remove_and_reset_members')
    def test_setup_volume_replication_async(
            self, mock_rm, mock_add, mock_model):
        extra_specs = deepcopy(self.extra_specs)
        extra_specs['rep_mode'] = utils.REP_ASYNC
        rep_status, rep_data, __ = (
            self.async_driver.common.setup_volume_replication(
                self.data.array, self.data.test_volume,
                self.data.device_id, extra_specs))
        self.assertEqual(fields.ReplicationStatus.ENABLED, rep_status)
        self.assertEqual({'array': self.data.remote_array,
                          'device_id': self.data.device_id}, rep_data)
        mock_add.assert_called_once()

    @mock.patch.object(common.PowerMaxCommon, '_failover_replication',
                       return_value=({}, {}))
    def test_failover_host_async(self, mock_fg):
        volumes = [self.data.test_volume]
        extra_specs = deepcopy(self.extra_specs)
        extra_specs['rep_mode'] = utils.REP_ASYNC
        with mock.patch.object(common.PowerMaxCommon, '_initial_setup',
                               return_value=extra_specs):
            self.async_driver.common.failover_host(volumes, None, [])
        mock_fg.assert_called_once()

    @mock.patch.object(common.PowerMaxCommon, '_retype_volume',
                       return_value=True)
    @mock.patch.object(masking.PowerMaxMasking,
                       'remove_vol_from_storage_group')
    @mock.patch.object(common.PowerMaxCommon, '_retype_remote_volume',
                       return_value=True)
    @mock.patch.object(
        common.PowerMaxCommon, 'setup_volume_replication',
        return_value=('', tpd.PowerMaxData.provider_location2, ''))
    @mock.patch.object(common.PowerMaxCommon,
                       '_remove_vol_and_cleanup_replication')
    @mock.patch.object(utils.PowerMaxUtils, 'is_replication_enabled',
                       side_effect=[False, True, True, False, True, True])
    def test_migrate_volume_replication(self, mock_re, mock_rm_rep,
                                        mock_setup, mock_retype,
                                        mock_rm, mock_rt):
        new_type = {'extra_specs': {}}
        for x in range(0, 3):
            success, model_update = self.common._migrate_volume(
                self.data.array, self.data.test_volume, self.data.device_id,
                self.data.srp, 'OLTP', 'Silver', self.data.test_volume.name,
                new_type, self.data.extra_specs)
            self.assertTrue(success)
        mock_rm_rep.assert_called_once()
        mock_setup.assert_called_once()
        mock_retype.assert_called_once()

    @mock.patch.object(
        common.PowerMaxCommon, '_get_replication_extra_specs',
        return_value=tpd.PowerMaxData.extra_specs_rep_enabled)
    @mock.patch.object(rest.PowerMaxRest, 'get_storage_groups_from_volume',
                       side_effect=[tpd.PowerMaxData.storagegroup_list,
                                    ['OS-SRP_1-Diamond-DSS-RE-SG']])
    @mock.patch.object(common.PowerMaxCommon, '_retype_volume',
                       return_value=True)
    def test_retype_volume_replication(self, mock_retype, mock_sg, mock_es):
        for x in range(0, 2):
            self.common._retype_remote_volume(
                self.data.array, self.data.test_volume, self.data.device_id,
                self.data.test_volume.name, utils.REP_SYNC,
                True, self.data.extra_specs)
        mock_retype.assert_called_once()
