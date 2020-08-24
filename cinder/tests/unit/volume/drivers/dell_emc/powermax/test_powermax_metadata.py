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

import platform
from unittest import mock

from cinder.objects import fields
from cinder.tests.unit import test
from cinder.tests.unit.volume.drivers.dell_emc.powermax import (
    powermax_data as tpd)
from cinder import version as openstack_version
from cinder.volume.drivers.dell_emc.powermax import metadata
from cinder.volume.drivers.dell_emc.powermax import rest
from cinder.volume.drivers.dell_emc.powermax import utils


class PowerMaxVolumeMetadataNoDebugTest(test.TestCase):
    def setUp(self):
        self.data = tpd.PowerMaxData()
        super(PowerMaxVolumeMetadataNoDebugTest, self).setUp()
        is_debug = False
        self.volume_metadata = metadata.PowerMaxVolumeMetadata(
            rest.PowerMaxRest, '4.0', is_debug)

    @mock.patch.object(
        metadata.PowerMaxVolumeMetadata, '_fill_volume_trace_dict',
        return_value={})
    def test_gather_volume_info(self, mock_fvtd):
        self.volume_metadata.gather_volume_info(
            self.data.volume_id, 'create', False, volume_size=1)
        mock_fvtd.assert_not_called()


class PowerMaxVolumeMetadataDebugTest(test.TestCase):
    def setUp(self):
        self.data = tpd.PowerMaxData()
        super(PowerMaxVolumeMetadataDebugTest, self).setUp()
        is_debug = True
        self.volume_metadata = metadata.PowerMaxVolumeMetadata(
            rest.PowerMaxRest, '4.1', is_debug)
        self.utils = self.volume_metadata.utils
        self.rest = self.volume_metadata.rest

    @mock.patch.object(
        metadata.PowerMaxVolumeMetadata, '_fill_volume_trace_dict',
        return_value={})
    def test_gather_volume_info(self, mock_fvtd):
        self.volume_metadata.gather_volume_info(
            self.data.volume_id, 'create', False, volume_size=1)
        mock_fvtd.assert_called_once()

    @mock.patch.object(
        metadata.PowerMaxVolumeMetadata, 'update_volume_info_metadata',
        return_value={})
    def test_capture_attach_info(self, mock_uvim):
        self.volume_metadata.capture_attach_info(
            self.data.test_volume, self.data.extra_specs,
            self.data.masking_view_dict, self.data.fake_host,
            False, False)
        mock_uvim.assert_called_once()

    @mock.patch.object(
        metadata.PowerMaxVolumeMetadata, 'update_volume_info_metadata',
        return_value={})
    def test_capture_attach_info_tags(self, mock_uvim):
        self.volume_metadata.capture_attach_info(
            self.data.test_volume, self.data.extra_specs,
            self.data.masking_view_dict_tags, self.data.fake_host,
            False, False)
        mock_uvim.assert_called_once()

    @mock.patch.object(
        metadata.PowerMaxVolumeMetadata, 'update_volume_info_metadata',
        return_value={})
    def test_capture_create_volume(self, mock_uvim):
        self.volume_metadata.capture_create_volume(
            self.data.device_id, self.data.test_volume, 'test_group',
            'test_group_id', self.data.extra_specs, {}, 'create', None)
        mock_uvim.assert_called_once()

    @mock.patch.object(
        metadata.PowerMaxVolumeMetadata, 'update_volume_info_metadata',
        return_value={})
    def test_capture_delete_info(self, mock_uvim):
        self.volume_metadata.capture_delete_info(self.data.test_volume)
        mock_uvim.assert_called_once()

    @mock.patch.object(
        metadata.PowerMaxVolumeMetadata, 'update_volume_info_metadata',
        return_value={})
    def test_capture_manage_existing(self, mock_uvim):
        self.volume_metadata.capture_manage_existing(
            self.data.test_volume, {}, self.data.device_id,
            self.data.extra_specs)
        mock_uvim.assert_called_once()

    @mock.patch.object(
        metadata.PowerMaxVolumeMetadata, 'update_volume_info_metadata',
        return_value={})
    def test_capture_failover_volume(self, mock_uvim):
        self.volume_metadata.capture_failover_volume(
            self.data.test_volume, self.data.device_id2,
            self.data.remote_array, self.data.rdf_group_name_1,
            self.data.device_id, self.data.array,
            self.data.extra_specs, True, None,
            fields.ReplicationStatus.FAILED_OVER, utils.REP_SYNC)
        mock_uvim.assert_called_once()

    @mock.patch.object(
        metadata.PowerMaxVolumeMetadata, 'update_volume_info_metadata',
        return_value={})
    def test_capture_modify_group(self, mock_uvim):
        self.volume_metadata.capture_modify_group(
            'test_group', 'test_group_id', [self.data.test_volume],
            [], self.data.array)
        mock_uvim.assert_called_once()

    @mock.patch.object(
        metadata.PowerMaxVolumeMetadata, 'update_volume_info_metadata',
        return_value={})
    def test_capture_extend_info(self, mock_uvim):
        self.volume_metadata.capture_extend_info(
            self.data.test_volume, 5, self.data.device_id,
            self.data.extra_specs, self.data.array)
        mock_uvim.assert_called_once()

    @mock.patch.object(
        metadata.PowerMaxVolumeMetadata, 'update_volume_info_metadata',
        return_value={})
    def test_capture_detach_info(self, mock_uvim):
        self.volume_metadata.capture_detach_info(
            self.data.test_volume, self.data.extra_specs, self.data.device_id,
            None, None)
        mock_uvim.assert_called_once()

    @mock.patch.object(
        metadata.PowerMaxVolumeMetadata, 'update_volume_info_metadata',
        return_value={})
    def test_capture_snapshot_info(self, mock_uvim):
        self.volume_metadata.capture_snapshot_info(
            self.data.test_volume, self.data.extra_specs, 'createSnapshot',
            self.data.snapshot_metadata)
        mock_uvim.assert_called_once()

    @mock.patch.object(
        metadata.PowerMaxVolumeMetadata, 'update_volume_info_metadata',
        return_value={})
    def test_capture_retype_info(self, mock_uvim):
        self.volume_metadata.capture_retype_info(
            self.data.test_volume, self.data.device_id, self.data.array,
            self.data.srp, self.data.slo, self.data.workload,
            self.data.storagegroup_name_target, False, None,
            False, None)
        mock_uvim.assert_called_once()

    def test_update_volume_info_metadata(self):
        volume_metadata = self.volume_metadata.update_volume_info_metadata(
            self.data.data_dict, self.data.version_dict)
        self.assertEqual('2.7.12', volume_metadata['python_version'])
        self.assertEqual('VMAX250F', volume_metadata['storage_model'])
        self.assertEqual('DSS', volume_metadata['workload'])
        self.assertEqual('OS-fibre-PG', volume_metadata['port_group'])

    def test_fill_volume_trace_dict(self):
        datadict = {}
        volume_trace_dict = {}
        volume_key_value = {}
        result_dict = {'successful_operation': 'create',
                       'volume_id': self.data.test_volume.id}
        volume_metadata = self.volume_metadata._fill_volume_trace_dict(
            self.data.test_volume.id, 'create', False, target_name=None,
            datadict=datadict, volume_key_value=volume_key_value,
            volume_trace_dict=volume_trace_dict)
        self.assertEqual(result_dict, volume_metadata)

    def test_fill_volume_trace_dict_multi_attach(self):
        mv_list = ['mv1', 'mv2', 'mv3']
        sg_list = ['sg1', 'sg2', 'sg3']
        datadict = {}
        volume_trace_dict = {}
        volume_key_value = {}
        result_dict = {
            'masking_view_1': 'mv1', 'masking_view_2': 'mv2',
            'masking_view_3': 'mv3', 'successful_operation': 'attach',
            'storage_group_1': 'sg1', 'storage_group_2': 'sg2',
            'storage_group_3': 'sg3', 'volume_id': self.data.test_volume.id}
        volume_metadata = self.volume_metadata._fill_volume_trace_dict(
            self.data.test_volume.id, 'attach', False, target_name=None,
            datadict=datadict, volume_trace_dict=volume_trace_dict,
            volume_key_value=volume_key_value, mv_list=mv_list,
            sg_list=sg_list)
        self.assertEqual(result_dict, volume_metadata)

    def test_fill_volume_trace_dict_array_tags(self):
        datadict = {}
        volume_trace_dict = {}
        volume_key_value = {}
        result_dict = {'successful_operation': 'create',
                       'volume_id': self.data.test_volume.id,
                       'array_tag_list': ['one', 'two']}
        volume_metadata = self.volume_metadata._fill_volume_trace_dict(
            self.data.test_volume.id, 'create', False, target_name=None,
            datadict=datadict, volume_key_value=volume_key_value,
            volume_trace_dict=volume_trace_dict,
            array_tag_list=['one', 'two'])
        self.assertEqual(result_dict, volume_metadata)

    @mock.patch.object(utils.PowerMaxUtils, 'merge_dicts',
                       return_value={})
    def test_consolidate_volume_trace_list(self, mock_m2d):
        self.volume_metadata.volume_trace_list = [self.data.data_dict]
        volume_trace_dict = {'volume_updated_time': '2018-03-06 16:51:40',
                             'operation': 'delete',
                             'volume_id': self.data.volume_id}
        volume_key_value = {self.data.volume_id: volume_trace_dict}
        self.volume_metadata._consolidate_volume_trace_list(
            self.data.volume_id, volume_trace_dict, volume_key_value)
        mock_m2d.assert_called_once()

    def test_merge_dicts_multiple(self):
        d1 = {'a': 1, 'b': 2}
        d2 = {'c': 3, 'd': 4}
        d3 = {'e': 5, 'f': 6}
        res_d = {'a': 1, 'b': 2, 'c': 3, 'd': 4, 'e': 5, 'f': 6}
        result_dict = self.utils.merge_dicts(
            d1, d2, d3)
        self.assertEqual(res_d, result_dict)

    def test_merge_dicts_multiple_2(self):
        d1 = {'a': 1, 'b': 2}
        d2 = {'b': 3, 'd': 4}
        d3 = {'d': 5, 'e': 6}
        res_d = {'a': 1, 'b': 2, 'd': 4, 'e': 6}
        result_dict = self.utils.merge_dicts(
            d1, d2, d3)
        self.assertEqual(res_d, result_dict)

    def test_merge_dicts(self):
        self.volume_metadata.volume_trace_list = [self.data.data_dict]
        volume_trace_dict = {'volume_updated_time': '2018-03-06 16:51:40',
                             'operation': 'delete',
                             'volume_id': self.data.volume_id}
        result_dict = self.utils.merge_dicts(
            volume_trace_dict, self.data.volume_info_dict)
        self.assertEqual('delete', result_dict['operation'])
        self.assertEqual(
            '2018-03-06 16:51:40', result_dict['volume_updated_time'])
        self.assertEqual('OS-fibre-PG', result_dict['port_group'])

    @mock.patch.object(platform, 'platform',
                       return_value=tpd.PowerMaxData.platform)
    @mock.patch.object(platform, 'python_version',
                       return_value=tpd.PowerMaxData.python_version)
    @mock.patch.object(openstack_version.version_info, 'version_string',
                       return_value=tpd.PowerMaxData.openstack_version)
    @mock.patch.object(openstack_version.version_info, 'release_string',
                       return_value=tpd.PowerMaxData.openstack_release)
    @mock.patch.object(
        rest.PowerMaxRest, 'get_unisphere_version',
        return_value={'version': tpd.PowerMaxData.unisphere_version})
    @mock.patch.object(
        rest.PowerMaxRest, 'get_array_detail',
        return_value={'ucode': tpd.PowerMaxData.vmax_firmware_version,
                      'model': tpd.PowerMaxData.vmax_model})
    def test_gather_version_info(
            self, mock_vi, mock_ur, mock_or, mock_ov, mock_pv, mock_p):
        self.volume_metadata.gather_version_info(self.data.array)
        self.assertEqual(
            self.data.version_dict, self.volume_metadata.version_dict)

    def test_gather_replication_info_target_model(self):
        rep_extra_specs = {'rep_mode': 'Synchronous',
                           'target_array_model': 'PowerMax_2000'}
        rdf_group_no = '70'
        remote_array = '000197800124'
        rep_config = {'mode': 'Synchronous',
                      'rdf_group_label': '23_24_007',
                      'portgroup': 'OS-fibre-PG',
                      'allow_extend': True,
                      'array': '000197800124',
                      'srp': 'SRP_2'}
        rep_info_dict = self.volume_metadata.gather_replication_info(
            self.data.volume_id, 'replication', False,
            rdf_group_no=rdf_group_no,
            target_name='target_name', remote_array=remote_array,
            target_device_id=self.data.device_id2,
            replication_status=fields.ReplicationStatus.ENABLED,
            rep_mode=rep_extra_specs['rep_mode'],
            rdf_group_label=rep_config['rdf_group_label'],
            target_array_model=rep_extra_specs['target_array_model'])
        self.assertEqual(
            'PowerMax_2000', rep_info_dict['target_array_model'])
