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
import time
from unittest import mock
from unittest.mock import call

import requests

from cinder import exception
from cinder.tests.unit import test
from cinder.tests.unit.volume.drivers.dell_emc.powermax import (
    powermax_data as tpd)
from cinder.tests.unit.volume.drivers.dell_emc.powermax import (
    powermax_fake_objects as tpfo)
from cinder.volume.drivers.dell_emc.powermax import fc
from cinder.volume.drivers.dell_emc.powermax import rest
from cinder.volume.drivers.dell_emc.powermax import utils
from cinder.volume import volume_utils


class PowerMaxRestTest(test.TestCase):
    def setUp(self):
        self.data = tpd.PowerMaxData()
        super(PowerMaxRestTest, self).setUp()
        volume_utils.get_max_over_subscription_ratio = mock.Mock()
        configuration = tpfo.FakeConfiguration(
            None, 'RestTests', 1, 1, san_ip='1.1.1.1', san_login='smc',
            powermax_array=self.data.array, powermax_srp='SRP_1',
            san_password='smc', san_api_port=8443,
            powermax_port_groups=[self.data.port_group_name_i])
        rest.PowerMaxRest._establish_rest_session = mock.Mock(
            return_value=tpfo.FakeRequestsSession())
        driver = fc.PowerMaxFCDriver(configuration=configuration)
        self.driver = driver
        self.common = self.driver.common
        self.rest = self.common.rest
        self.rest.is_snap_id = True
        self.utils = self.common.utils

    def test_rest_request_no_response(self):
        with mock.patch.object(self.rest.session, 'request',
                               return_value=tpfo.FakeResponse(None, None)):
            sc, msg = self.rest.request('TIMEOUT', '/fake_url')
            self.assertIsNone(sc)
            self.assertIsNone(msg)

    def test_rest_request_timeout_exception(self):
        self.assertRaises(requests.exceptions.Timeout,
                          self.rest.request, '', 'TIMEOUT')

    def test_rest_request_connection_exception(self):
        self.assertRaises(requests.exceptions.ConnectionError,
                          self.rest.request, '', 'CONNECTION')

    def test_rest_request_http_exception(self):
        self.assertRaises(requests.exceptions.HTTPError,
                          self.rest.request, '', 'HTTP')

    def test_rest_request_ssl_exception(self):
        self.assertRaises(requests.exceptions.SSLError,
                          self.rest.request, '', 'SSL')

    def test_rest_request_undefined_exception(self):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.rest.request, '', 'EXCEPTION')

    def test_rest_request_handle_failover(self):
        response = tpfo.FakeResponse(200, 'Success')
        with mock.patch.object(self.rest, '_handle_u4p_failover')as mock_fail:
            with mock.patch.object(self.rest.session, 'request',
                                   side_effect=[requests.ConnectionError,
                                                response]):
                self.rest.u4p_failover_enabled = True
                self.rest.request('/fake_uri', 'GET')
                mock_fail.assert_called_once()

    @mock.patch.object(time, 'sleep')
    def test_rest_request_failover_escape(self, mck_sleep):
        self.rest.u4p_failover_lock = True
        response = tpfo.FakeResponse(200, 'Success')
        with mock.patch.object(self.rest, '_handle_u4p_failover')as mock_fail:
            with mock.patch.object(self.rest.session, 'request',
                                   side_effect=[requests.ConnectionError,
                                                response]):
                self.rest.u4p_failover_enabled = True
                self.rest.request('/fake_uri', 'GET')
                mock_fail.assert_called_once()
        self.rest.u4p_failover_lock = False

    def test_wait_for_job_complete(self):
        rc, job, status, task = self.rest.wait_for_job_complete(
            {'status': 'created', 'jobId': '12345'}, self.data.extra_specs)
        self.assertEqual(0, rc)

    def test_wait_for_job_complete_failed(self):
        with mock.patch.object(self.rest, '_is_job_finished',
                               side_effect=exception.BadHTTPResponseStatus):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.rest.wait_for_job_complete,
                              self.data.job_list[0], self.data.extra_specs)

    def test_is_job_finished_false(self):
        job_id = '55555'
        complete, response, rc, status, task = self.rest._is_job_finished(
            job_id)
        self.assertFalse(complete)

    def test_is_job_finished_failed(self):
        job_id = '55555'
        complete, response, rc, status, task = self.rest._is_job_finished(
            job_id)
        self.assertFalse(complete)
        with mock.patch.object(self.rest, 'request',
                               return_value=(200, {'status': 'FAILED'})):
            complete, response, rc, status, task = self.rest._is_job_finished(
                job_id)
            self.assertTrue(complete)
            self.assertEqual(-1, rc)

    def test_check_status_code_success(self):
        status_code = 200
        self.rest.check_status_code_success('test success', status_code, "")

    def test_check_status_code_not_success(self):
        status_code = 500
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.rest.check_status_code_success,
                          'test exception', status_code, "")

    def test_wait_for_job_success(self):
        operation = 'test'
        status_code = 202
        job = self.data.job_list[0]
        extra_specs = self.data.extra_specs
        self.rest.wait_for_job(operation, status_code, job, extra_specs)

    def test_wait_for_job_failed(self):
        operation = 'test'
        status_code = 202
        job = self.data.job_list[2]
        extra_specs = self.data.extra_specs
        with mock.patch.object(self.rest, 'wait_for_job_complete',
                               return_value=(-1, '', '', '')):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.rest.wait_for_job,
                              operation, status_code, job, extra_specs)

    def test_get_resource_present(self):
        array = self.data.array
        category = 'sloprovisioning'
        resource_type = 'storagegroup'
        resource = self.rest.get_resource(array, category, resource_type)
        self.assertEqual(self.data.sg_list, resource)

    def test_get_resource_not_present(self):
        array = self.data.array
        category = 'sloprovisioning'
        resource_type = self.data.failed_resource
        resource = self.rest.get_resource(array, category, resource_type)
        self.assertIsNone(resource)

    def test_create_resource_success(self):
        array = self.data.array
        category = ''
        resource_type = ''
        payload = {'someKey': 'someValue'}
        status_code, message = self.rest.create_resource(
            array, category, resource_type, payload)
        self.assertEqual(self.data.job_list[0], message)

    def test_create_resource_failed(self):
        array = self.data.array
        category = ''
        resource_type = ''
        payload = {'someKey': self.data.failed_resource}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.rest.create_resource, array, category,
                          resource_type, payload)

    def test_modify_resource(self):
        array = self.data.array
        category = ''
        resource_type = ''
        payload = {'someKey': 'someValue'}
        status_code, message = self.rest.modify_resource(
            array, category, resource_type, payload)
        self.assertEqual(self.data.job_list[0], message)

    def test_modify_resource_failed(self):
        array = self.data.array
        category = ''
        resource_type = ''
        payload = {'someKey': self.data.failed_resource}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.rest.modify_resource, array, category,
                          resource_type, payload)

    def test_delete_resource(self):
        operation = 'delete res resource'
        status_code = 204
        message = None
        array = self.data.array
        category = 'cat'
        resource_type = 'res'
        resource_name = 'name'
        with mock.patch.object(self.rest, 'check_status_code_success'):
            self.rest.delete_resource(
                array, category, resource_type, resource_name)
            self.rest.check_status_code_success.assert_called_with(
                operation, status_code, message)

    def test_delete_resource_failed(self):
        array = self.data.array
        category = self.data.failed_resource
        resource_type = self.data.failed_resource
        resource_name = self.data.failed_resource
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.rest.modify_resource, array, category,
                          resource_type, resource_name)

    def test_get_arrays_list(self):
        ret_val = {'symmetrixId': tpd.PowerMaxData.array}
        with mock.patch.object(self.rest, 'get_request',
                               return_value=ret_val):
            ref_details = self.data.array
            array_details = self.rest.get_arrays_list()
            self.assertEqual(ref_details, array_details)

    def test_get_arrays_list_failed(self):
        with mock.patch.object(self.rest, 'get_request',
                               return_value=dict()):
            array_details = self.rest.get_arrays_list()
            self.assertEqual(list(), array_details)

    def test_get_array_detail(self):
        ref_details = self.data.symmetrix[0]
        array_details = self.rest.get_array_detail(self.data.array)
        self.assertEqual(ref_details, array_details)

    def test_get_array_detail_failed(self):
        array_details = self.rest.get_array_detail(self.data.failed_resource)
        self.assertIsNone(array_details)

    def test_get_uni_version_success(self):
        ret_val = (200, tpd.PowerMaxData.version_details)
        current_major_version = tpd.PowerMaxData.u4v_version
        with mock.patch.object(self.rest, 'request', return_value=ret_val):
            version, major_version = self.rest.get_uni_version()
            self.assertIsNotNone(version)
            self.assertIsNotNone(major_version)
            self.assertEqual(major_version, current_major_version)

    def test_get_uni_version_failed(self):
        ret_val = (500, '')
        with mock.patch.object(self.rest, 'request', return_value=ret_val):
            version, major_version = self.rest.get_uni_version()
            self.assertIsNone(version)
            self.assertIsNone(major_version)

    def test_get_srp_by_name(self):
        ref_details = self.data.srp_details
        srp_details = self.rest.get_srp_by_name(
            self.data.array, self.data.srp)
        self.assertEqual(ref_details, srp_details)

    def test_get_slo_list_powermax(self):
        ref_settings = self.data.powermax_slo_details['sloId']
        slo_settings = self.rest.get_slo_list(
            self.data.array, True, 'PowerMax 2000')
        self.assertEqual(ref_settings, slo_settings)

    def test_get_slo_list_vmax(self):
        ref_settings = ['Diamond']
        with mock.patch.object(self.rest, 'get_resource',
                               return_value=self.data.vmax_slo_details):
            slo_settings = self.rest.get_slo_list(
                self.data.array, False, 'VMAX250F')
            self.assertEqual(ref_settings, slo_settings)

    def test_get_workload_settings(self):
        ref_settings = self.data.workloadtype['workloadId']
        wl_settings = self.rest.get_workload_settings(
            self.data.array, False)
        self.assertEqual(ref_settings, wl_settings)

    def test_get_workload_settings_next_gen(self):
        wl_settings = self.rest.get_workload_settings(
            self.data.array_herc, True)
        self.assertEqual(['None'], wl_settings)

    def test_get_workload_settings_failed(self):
        wl_settings = self.rest.get_workload_settings(
            self.data.failed_resource, False)
        self.assertEqual([], wl_settings)

    def test_is_compression_capable_true(self):
        compr_capable = self.rest.is_compression_capable('000197800128')
        self.assertTrue(compr_capable)

    def test_is_compression_capable_false(self):
        compr_capable = self.rest.is_compression_capable(self.data.array)
        self.assertFalse(compr_capable)
        with mock.patch.object(self.rest, 'request', return_value=(200, {})):
            compr_capable = self.rest.is_compression_capable(self.data.array)
            self.assertFalse(compr_capable)

    def test_get_storage_group(self):
        ref_details = self.data.sg_details[0]
        sg_details = self.rest.get_storage_group(
            self.data.array, self.data.defaultstoragegroup_name)
        self.assertEqual(ref_details, sg_details)

    def test_get_storage_group_list(self):
        sg_list = self.rest.get_storage_group_list(self.data.array)
        self.assertEqual(self.data.sg_list, sg_list)

    def test_create_storage_group(self):
        with mock.patch.object(self.rest, 'create_resource') as mock_create:
            payload = {'someKey': 'someValue'}
            self.rest._create_storagegroup(self.data.array, payload)
            mock_create.assert_called_once_with(
                self.data.array, 'sloprovisioning', 'storagegroup', payload)

    def test_create_storage_group_success(self):
        sg_name = self.rest.create_storage_group(
            self.data.array, self.data.storagegroup_name_f, self.data.srp,
            self.data.slo, self.data.workload, self.data.extra_specs)
        self.assertEqual(self.data.storagegroup_name_f, sg_name)

    def test_create_storage_group_next_gen(self):
        with mock.patch.object(self.rest, 'is_next_gen_array',
                               return_value=True):
            with mock.patch.object(
                    self.rest, '_create_storagegroup',
                    return_value=(200, self.data.job_list[0])) as mock_sg:
                self.rest.create_storage_group(
                    self.data.array, self.data.storagegroup_name_f,
                    self.data.srp, self.data.slo, self.data.workload,
                    self.data.extra_specs)
                payload = {'srpId': self.data.srp,
                           'storageGroupId': self.data.storagegroup_name_f,
                           'emulation': 'FBA',
                           'sloBasedStorageGroupParam': [
                               {'sloId': self.data.slo,
                                'workloadSelection': 'NONE',
                                'volumeAttributes': [{
                                    'volume_size': '0',
                                    'capacityUnit': 'GB',
                                    'num_of_vols': 0}]}]}
                mock_sg.assert_called_once_with(self.data.array, payload)

    def test_create_storage_group_failed(self):
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.rest.create_storage_group, self.data.array,
            self.data.failed_resource, self.data.srp, self.data.slo,
            self.data.workload, self.data.extra_specs)

    def test_create_storage_group_no_slo(self):
        sg_name = self.rest.create_storage_group(
            self.data.array, self.data.default_sg_no_slo, self.data.srp,
            None, None, self.data.extra_specs)
        self.assertEqual(self.data.default_sg_no_slo, sg_name)

    def test_create_storage_group_compression_disabled(self):
        with mock.patch.object(
                self.rest, '_create_storagegroup',
                return_value=(200, self.data.job_list[0]))as mock_sg:
            self.rest.create_storage_group(
                self.data.array, self.data.default_sg_compr_disabled,
                self.data.srp, self.data.slo, self.data.workload,
                self.data.extra_specs, True)
            payload = {'srpId': self.data.srp,
                       'storageGroupId': self.data.default_sg_compr_disabled,
                       'emulation': 'FBA',
                       'sloBasedStorageGroupParam': [
                           {'sloId': self.data.slo,
                            'workloadSelection': self.data.workload,
                            'volumeAttributes': [{
                                'volume_size': '0',
                                'capacityUnit': 'GB',
                                'num_of_vols': 0}],
                            'noCompression': 'true'}]}
            mock_sg.assert_called_once_with(self.data.array, payload)

    def test_modify_storage_group(self):
        array = self.data.array
        storagegroup = self.data.defaultstoragegroup_name
        return_message = self.data.add_volume_sg_info_dict
        payload = (
            {"executionOption": "ASYNCHRONOUS",
             "editStorageGroupActionParam": {
                 "expandStorageGroupParam": {
                     "addVolumeParam": {
                         "emulation": "FBA",
                         "create_new_volumes": "False",
                         "volumeAttributes": [
                             {
                                 "num_of_vols": 1,
                                 "volumeIdentifier": {
                                     "identifier_name": "os-123-456",
                                     "volumeIdentifierChoice":
                                         "identifier_name"
                                 },
                                 "volume_size": 1,
                                 "capacityUnit": "GB"}]}}}})
        version = self.data.u4v_version
        with mock.patch.object(self.rest, 'modify_resource',
                               return_value=(200,
                                             return_message)) as mock_modify:
            status_code, message = self.rest.modify_storage_group(
                array, storagegroup, payload)
            mock_modify.assert_called_once_with(
                self.data.array, 'sloprovisioning', 'storagegroup',
                payload, version, resource_name=storagegroup)
            self.assertEqual(1, mock_modify.call_count)
            self.assertEqual(200, status_code)
            self.assertEqual(return_message, message)

    def test_create_volume_from_sg_success(self):
        volume_name = self.data.volume_details[0]['volume_identifier']
        ref_dict = self.data.provider_location
        volume_dict = self.rest.create_volume_from_sg(
            self.data.array, volume_name, self.data.defaultstoragegroup_name,
            self.data.test_volume.size, self.data.extra_specs)
        self.assertEqual(ref_dict, volume_dict)

    @mock.patch.object(rest.PowerMaxRest, 'get_volume')
    @mock.patch.object(rest.PowerMaxRest, 'wait_for_job',
                       return_value=tpd.PowerMaxData.vol_create_task)
    def test_create_volume_from_sg_existing_volume_success(
            self, mock_task, mock_get):
        volume_name = self.data.volume_details[0]['volume_identifier']
        self.rest.create_volume_from_sg(
            self.data.array, volume_name, self.data.defaultstoragegroup_name,
            self.data.test_volume.size, self.data.extra_specs)
        mock_get.assert_called_with(self.data.array, self.data.device_id)

    def test_create_volume_from_sg_failed(self):
        volume_name = self.data.volume_details[0]['volume_identifier']
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.rest.create_volume_from_sg, self.data.array,
            volume_name, self.data.failed_resource,
            self.data.test_volume.size, self.data.extra_specs)

    def test_create_volume_from_sg_cannot_retrieve_device_id(self):
        with mock.patch.object(self.rest, 'find_volume_device_id',
                               return_value=None):
            volume_name = self.data.volume_details[0]['volume_identifier']
            self.assertRaises(
                exception.VolumeBackendAPIException,
                self.rest.create_volume_from_sg, self.data.array,
                volume_name, self.data.failed_resource,
                self.data.test_volume.size, self.data.extra_specs)

    @mock.patch.object(rest.PowerMaxRest, 'rename_volume')
    @mock.patch.object(rest.PowerMaxRest, 'get_volume_list',
                       return_value=['00001', '00002', '00003', '00004'])
    @mock.patch.object(rest.PowerMaxRest, 'wait_for_job')
    @mock.patch.object(rest.PowerMaxRest, 'modify_storage_group',
                       return_value=(200, 'job'))
    def test_create_volume_from_sg_rep_info(
            self, mck_modify, mck_wait, mck_get_vol, mck_rename):
        volume_name = self.data.volume_details[0]['volume_identifier']
        sg_name = self.data.defaultstoragegroup_name
        rep_info = self.data.rep_info_dict
        rep_info['initial_device_list'] = ['00001', '00002', '00003']
        ref_payload = self.data.create_vol_with_replication_payload
        ref_volume_dict = {utils.ARRAY: self.data.array,
                           utils.DEVICE_ID: '00004'}

        volume_dict = self.rest.create_volume_from_sg(
            self.data.array, volume_name, sg_name,
            self.data.test_volume.size, self.data.extra_specs, rep_info)
        mck_modify.assert_called_once_with(
            self.data.array, self.data.defaultstoragegroup_name, ref_payload)
        self.assertEqual(ref_volume_dict, volume_dict)

    @mock.patch.object(rest.PowerMaxRest, 'get_volume_list',
                       return_value=['00001', '00002', '00003', '00004'])
    @mock.patch.object(rest.PowerMaxRest, 'wait_for_job')
    @mock.patch.object(rest.PowerMaxRest, 'modify_storage_group',
                       return_value=(200, 'job'))
    def test_create_volume_from_sg_rep_info_vol_cnt_exception(
            self, mck_modify, mck_wait, mck_get_vol):
        volume_name = self.data.volume_details[0]['volume_identifier']
        sg_name = self.data.defaultstoragegroup_name
        rep_info = self.data.rep_info_dict
        rep_info['initial_device_list'] = ['00001', '00002']
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.rest.create_volume_from_sg, self.data.array,
                          volume_name, sg_name, self.data.test_volume.size,
                          self.data.extra_specs, rep_info)

    def test_add_vol_to_sg_success(self):
        operation = 'Add volume to sg'
        status_code = 202
        message = self.data.job_list[0]
        with mock.patch.object(self.rest, 'wait_for_job') as mock_wait:
            device_id = self.data.device_id
            self.rest.add_vol_to_sg(
                self.data.array, self.data.storagegroup_name_f, device_id,
                self.data.extra_specs)
            mock_wait.assert_called_with(
                operation, status_code, message, self.data.extra_specs)

    def test_add_vol_to_sg_failed(self):
        device_id = [self.data.device_id]
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.rest.add_vol_to_sg, self.data.array,
                          self.data.failed_resource, device_id,
                          self.data.extra_specs)

    def test_remove_vol_from_sg_success(self):
        operation = 'Remove vol from sg'
        status_code = 202
        message = self.data.job_list[0]
        with mock.patch.object(self.rest, 'wait_for_job') as mock_wait:
            device_id = self.data.device_id
            self.rest.remove_vol_from_sg(
                self.data.array, self.data.storagegroup_name_f, device_id,
                self.data.extra_specs)
            mock_wait.assert_called_with(
                operation, status_code, message, self.data.extra_specs)

    @mock.patch.object(time, 'sleep')
    def test_remove_vol_from_sg_failed(self, mock_sleep):
        device_id = [self.data.volume_details[0]['volumeId']]
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.rest.remove_vol_from_sg, self.data.array,
                          self.data.failed_resource, device_id,
                          self.data.extra_specs)

    @mock.patch.object(rest.PowerMaxRest, 'wait_for_job')
    def test_remove_vol_from_sg_force_true(self, mck_wait):
        device_id = self.data.device_id
        extra_specs = deepcopy(self.data.extra_specs)
        extra_specs[utils.FORCE_VOL_EDIT] = True
        expected_payload = (
            {"executionOption": "ASYNCHRONOUS",
             "editStorageGroupActionParam": {
                 "removeVolumeParam": {
                     "volumeId": [device_id],
                     "remoteSymmSGInfoParam": {
                         "force": "true"}}}})
        with mock.patch.object(
                self.rest, 'modify_storage_group', return_value=(
                    200, tpd.PowerMaxData.job_list)) as mck_mod:
            self.rest.remove_vol_from_sg(
                self.data.array, self.data.storagegroup_name_f, device_id,
                extra_specs)
            mck_mod.assert_called_with(
                self.data.array, self.data.storagegroup_name_f,
                expected_payload)

    @mock.patch.object(rest.PowerMaxRest, 'wait_for_job')
    def test_remove_vol_from_sg_force_false(self, mck_wait):
        device_id = self.data.device_id
        extra_specs = deepcopy(self.data.extra_specs)
        extra_specs.pop(utils.FORCE_VOL_EDIT, None)
        expected_payload = (
            {"executionOption": "ASYNCHRONOUS",
             "editStorageGroupActionParam": {
                 "removeVolumeParam": {
                     "volumeId": [device_id],
                     "remoteSymmSGInfoParam": {
                         "force": "false"}}}})
        with mock.patch.object(
                self.rest, 'modify_storage_group', return_value=(
                    200, tpd.PowerMaxData.job_list)) as mck_mod:
            self.rest.remove_vol_from_sg(
                self.data.array, self.data.storagegroup_name_f, device_id,
                extra_specs)
            mck_mod.assert_called_with(
                self.data.array, self.data.storagegroup_name_f,
                expected_payload)

    def test_get_vmax_default_storage_group(self):
        ref_storage_group = self.data.sg_details[0]
        ref_sg_name = self.data.defaultstoragegroup_name
        storagegroup, storagegroup_name = (
            self.rest.get_vmax_default_storage_group(
                self.data.array, self.data.srp,
                self.data.slo, self.data.workload))
        self.assertEqual(ref_sg_name, storagegroup_name)
        self.assertEqual(ref_storage_group, storagegroup)

    def test_get_vmax_default_storage_group_next_gen(self):
        with mock.patch.object(self.rest, 'is_next_gen_array',
                               return_value=True):
            __, storagegroup_name = self.rest.get_vmax_default_storage_group(
                self.data.array, self.data.srp,
                self.data.slo, self.data.workload)
            self.assertEqual('OS-SRP_1-Diamond-NONE-SG', storagegroup_name)

    def test_delete_storage_group(self):
        operation = 'delete storagegroup resource'
        status_code = 204
        message = None
        with mock.patch.object(
                self.rest, 'check_status_code_success') as mock_check:
            self.rest.delete_storage_group(
                self.data.array, self.data.storagegroup_name_f)
            mock_check.assert_called_with(operation, status_code, message)

    def test_is_child_sg_in_parent_sg(self):
        is_child1 = self.rest.is_child_sg_in_parent_sg(
            self.data.array, self.data.storagegroup_name_f,
            self.data.parent_sg_f)
        is_child2 = self.rest.is_child_sg_in_parent_sg(
            self.data.array, self.data.defaultstoragegroup_name,
            self.data.parent_sg_f)
        self.assertTrue(is_child1)
        self.assertFalse(is_child2)

    def test_is_child_sg_in_parent_sg_case_not_matching(self):
        lower_case_host = 'OS-hostx-SRP_1-DiamondDSS-os-fibre-PG'

        is_child1 = self.rest.is_child_sg_in_parent_sg(
            self.data.array, lower_case_host,
            self.data.parent_sg_f)
        self.assertTrue(is_child1)

    def test_is_child_sg_in_parent_sg_spelling_mistake(self):
        lower_case_host = 'OS-hosty-SRP_1-DiamondDSS-os-fiber-PG'

        is_child1 = self.rest.is_child_sg_in_parent_sg(
            self.data.array, lower_case_host,
            self.data.parent_sg_f)
        self.assertFalse(is_child1)

    def test_add_child_sg_to_parent_sg(self):
        payload = {'editStorageGroupActionParam': {
            'expandStorageGroupParam': {
                'addExistingStorageGroupParam': {
                    'storageGroupId': [self.data.storagegroup_name_f]}}}}
        with mock.patch.object(
                self.rest, 'modify_storage_group',
                return_value=(202, self.data.job_list[0])) as mck_mod_sg:
            self.rest.add_child_sg_to_parent_sg(
                self.data.array, self.data.storagegroup_name_f,
                self.data.parent_sg_f, self.data.extra_specs)
            mck_mod_sg.assert_called_once_with(
                self.data.array, self.data.parent_sg_f, payload)

    def test_remove_child_sg_from_parent_sg(self):
        payload = {'editStorageGroupActionParam': {
            'removeStorageGroupParam': {
                'storageGroupId': [self.data.storagegroup_name_f],
                'force': 'true'}}}
        with mock.patch.object(
                self.rest, 'modify_storage_group',
                return_value=(202, self.data.job_list[0])) as mock_modify:
            self.rest.remove_child_sg_from_parent_sg(
                self.data.array, self.data.storagegroup_name_f,
                self.data.parent_sg_f, self.data.extra_specs)
            mock_modify.assert_called_once_with(
                self.data.array, self.data.parent_sg_f, payload)

    def test_get_volume_list(self):
        ref_volumes = [self.data.device_id, self.data.device_id2]
        volumes = self.rest.get_volume_list(self.data.array, {})
        self.assertEqual(ref_volumes, volumes)

    def test_get_volume(self):
        ref_volumes = self.data.volume_details[0]
        device_id = self.data.device_id
        volumes = self.rest.get_volume(self.data.array, device_id)
        self.assertEqual(ref_volumes, volumes)

    def test_get_private_volume(self):
        device_id = self.data.device_id
        ref_volume = self.data.private_vol_details['resultList']['result'][0]
        volume = self.rest._get_private_volume(self.data.array, device_id)
        self.assertEqual(ref_volume, volume)

    def test_get_private_volume_exception(self):
        device_id = self.data.device_id
        with mock.patch.object(self.rest, 'get_resource',
                               return_value={}):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.rest._get_private_volume,
                              self.data.array, device_id)

    def test_modify_volume_success(self):
        array = self.data.array
        device_id = self.data.device_id
        payload = {'someKey': 'someValue'}
        with mock.patch.object(self.rest, 'modify_resource') as mock_modify:
            self.rest._modify_volume(array, device_id, payload)
            mock_modify.assert_called_once_with(
                self.data.array, 'sloprovisioning', 'volume',
                payload, resource_name=device_id)

    def test_modify_volume_failed(self):
        payload = {'someKey': self.data.failed_resource}
        device_id = self.data.device_id
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.rest._modify_volume, self.data.array,
            device_id, payload)

    @mock.patch.object(rest.PowerMaxRest, 'wait_for_job')
    def test_extend_volume(self, mck_wait):
        array = self.data.array
        device_id = self.data.device_id
        new_size = '3'
        extra_specs = self.data.extra_specs
        rdfg_num = self.data.rdf_group_no_1

        extend_vol_payload = {'executionOption': 'ASYNCHRONOUS',
                              'editVolumeActionParam': {
                                  'expandVolumeParam': {
                                      'volumeAttribute': {
                                          'volume_size': new_size,
                                          'capacityUnit': 'GB'},
                                      'rdfGroupNumber': rdfg_num}}}

        with mock.patch.object(
                self.rest, '_modify_volume',
                return_value=(202, self.data.job_list[0])) as mck_modify:

            self.rest.extend_volume(array, device_id, new_size, extra_specs,
                                    rdfg_num)

            mck_modify.assert_called_once_with(array, device_id,
                                               extend_vol_payload)

    def test_legacy_delete_volume(self):
        device_id = self.data.device_id
        vb_except = exception.VolumeBackendAPIException
        with mock.patch.object(self.rest, 'delete_resource') as mock_delete, (
                mock.patch.object(
                    self.rest, '_modify_volume',
                    side_effect=[None, None, None, vb_except])) as mock_modify:
            for _ in range(0, 2):
                self.rest.delete_volume(self.data.array, device_id)
            mod_call_count = mock_modify.call_count
            self.assertEqual(4, mod_call_count)
            mock_delete.assert_called_once_with(
                self.data.array, 'sloprovisioning', 'volume', device_id)

    def test_delete_volume(self):
        device_id = self.data.device_id
        self.rest.ucode_major_level = utils.UCODE_5978
        self.rest.ucode_minor_level = utils.UCODE_5978_HICKORY
        with mock.patch.object(
            self.rest, 'delete_resource') as mock_delete, (
                mock.patch.object(
                    self.rest, '_modify_volume')) as mock_modify:

            self.rest.delete_volume(self.data.array, device_id)
            mod_call_count = mock_modify.call_count
            self.assertEqual(1, mod_call_count)
            mock_delete.assert_called_once_with(
                self.data.array, 'sloprovisioning', 'volume', device_id)

    def test_rename_volume(self):
        device_id = self.data.device_id
        payload = {'editVolumeActionParam': {
            'modifyVolumeIdentifierParam': {
                'volumeIdentifier': {
                    'identifier_name': 'new_name',
                    'volumeIdentifierChoice': 'identifier_name'}}}}
        payload2 = {'editVolumeActionParam': {'modifyVolumeIdentifierParam': {
            'volumeIdentifier': {'volumeIdentifierChoice': 'none'}}}}
        with mock.patch.object(self.rest, '_modify_volume') as mock_mod:
            self.rest.rename_volume(self.data.array, device_id, 'new_name')
            mock_mod.assert_called_once_with(
                self.data.array, device_id, payload)
            mock_mod.reset_mock()
            self.rest.rename_volume(self.data.array, device_id, None)
            mock_mod.assert_called_once_with(
                self.data.array, device_id, payload2)

    def test_check_volume_device_id(self):
        element_name = self.utils.get_volume_element_name(
            self.data.test_volume.id)
        found_dev_id = self.rest.check_volume_device_id(
            self.data.array, self.data.device_id, element_name)
        self.assertEqual(self.data.device_id, found_dev_id)
        found_dev_id2 = self.rest.check_volume_device_id(
            self.data.array, self.data.device_id3, element_name)
        self.assertIsNone(found_dev_id2)

    def test_check_volume_device_id_host_migration_case(self):
        element_name = self.utils.get_volume_element_name(
            self.data.test_clone_volume.id)
        found_dev_id = self.rest.check_volume_device_id(
            self.data.array, self.data.device_id, element_name,
            name_id=self.data.test_clone_volume._name_id)
        self.assertEqual(self.data.device_id, found_dev_id)

    def test_check_volume_device_id_legacy_case(self):
        element_name = self.utils.get_volume_element_name(
            self.data.test_volume.id)
        with mock.patch.object(self.rest, 'get_volume',
                               return_value=self.data.volume_details_legacy):
            found_dev_id = self.rest.check_volume_device_id(
                self.data.array, self.data.device_id, element_name)
        self.assertEqual(self.data.device_id, found_dev_id)

    def test_check_volume_device_id_legacy_case_no_match(self):
        element_name = self.utils.get_volume_element_name(
            self.data.test_volume.id)
        volume_details_no_match = deepcopy(self.data.volume_details_legacy)
        volume_details_no_match['volume_identifier'] = 'no_match'
        with mock.patch.object(self.rest, 'get_volume',
                               return_value=volume_details_no_match):
            found_dev_id = self.rest.check_volume_device_id(
                self.data.array, self.data.device_id, element_name)
        self.assertIsNone(found_dev_id)

    def test_check_volume_device_id_volume_identifier_none(self):
        element_name = self.utils.get_volume_element_name(
            self.data.test_volume.id)
        vol_details_vol_identifier_none = deepcopy(
            self.data.volume_details_legacy)
        vol_details_vol_identifier_none['volume_identifier'] = None
        with mock.patch.object(self.rest, 'get_volume',
                               return_value=vol_details_vol_identifier_none):
            found_dev_id = self.rest.check_volume_device_id(
                self.data.array, self.data.device_id, element_name)
        self.assertIsNone(found_dev_id)

    def test_find_mv_connections_for_vol(self):
        device_id = self.data.device_id
        ref_lun_id = int(
            (self.data.maskingview[0]['maskingViewConnection'][0][
                'host_lun_address']), 16)
        host_lun_id = self.rest.find_mv_connections_for_vol(
            self.data.array, self.data.masking_view_name_f, device_id)
        self.assertEqual(ref_lun_id, host_lun_id)

    def test_find_mv_connections_for_vol_failed(self):
        # no masking view info retrieved
        device_id = self.data.volume_details[0]['volumeId']
        host_lun_id = self.rest.find_mv_connections_for_vol(
            self.data.array, self.data.failed_resource, device_id)
        self.assertIsNone(host_lun_id)
        # no connection info received
        with mock.patch.object(self.rest, 'get_resource',
                               return_value={'no_conn': 'no_info'}):
            host_lun_id2 = self.rest.find_mv_connections_for_vol(
                self.data.array, self.data.masking_view_name_f, device_id)
            self.assertIsNone(host_lun_id2)

    def test_get_storage_groups_from_volume(self):
        array = self.data.array
        device_id = self.data.device_id
        ref_list = self.data.volume_details[0]['storageGroupId']
        sg_list = self.rest.get_storage_groups_from_volume(array, device_id)
        self.assertEqual(ref_list, sg_list)

    def test_get_num_vols_in_sg(self):
        num_vol = self.rest.get_num_vols_in_sg(
            self.data.array, self.data.defaultstoragegroup_name)
        self.assertEqual(2, num_vol)

    def test_get_num_vols_in_sg_no_num(self):
        with mock.patch.object(self.rest, 'get_storage_group',
                               return_value={}):
            num_vol = self.rest.get_num_vols_in_sg(
                self.data.array, self.data.defaultstoragegroup_name)
            self.assertEqual(0, num_vol)

    def test_is_volume_in_storagegroup(self):
        # True
        array = self.data.array
        device_id = self.data.device_id
        storagegroup = self.data.defaultstoragegroup_name
        is_vol1 = self.rest.is_volume_in_storagegroup(
            array, device_id, storagegroup)
        # False
        with mock.patch.object(self.rest, 'get_storage_groups_from_volume',
                               return_value=[]):
            is_vol2 = self.rest.is_volume_in_storagegroup(
                array, device_id, storagegroup)
        self.assertTrue(is_vol1)
        self.assertFalse(is_vol2)

    def test_find_volume_device_number(self):
        array = self.data.array
        volume_name = self.data.volume_details[0]['volume_identifier']
        ref_device = self.data.device_id
        device_number = self.rest.find_volume_device_id(array, volume_name)
        self.assertEqual(ref_device, device_number)

    def test_find_volume_device_number_failed(self):
        array = self.data.array
        with mock.patch.object(self.rest, 'get_volume_list',
                               return_value=[]):
            device_number = self.rest.find_volume_device_id(array, 'name')
            self.assertIsNone(device_number)

    def test_get_volume_success(self):
        array = self.data.array
        device_id = self.data.device_id
        ref_volume = self.data.volume_details[0]
        volume = self.rest.get_volume(array, device_id)
        self.assertEqual(ref_volume, volume)

    def test_get_volume_failed(self):
        array = self.data.array
        device_id = self.data.failed_resource
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.rest.get_volume,
                          array, device_id)

    def test_find_volume_identifier(self):
        array = self.data.array
        device_id = self.data.device_id
        ref_name = self.data.volume_details[0]['volume_identifier']
        vol_name = self.rest.find_volume_identifier(array, device_id)
        self.assertEqual(ref_name, vol_name)

    def test_get_volume_size(self):
        array = self.data.array
        device_id = self.data.device_id
        ref_size = self.data.test_volume.size
        size = self.rest.get_size_of_device_on_array(array, device_id)
        self.assertEqual(ref_size, size)

    def test_get_volume_size_exception(self):
        array = self.data.array
        device_id = self.data.device_id
        with mock.patch.object(self.rest, 'get_volume',
                               return_value=None):
            size = self.rest.get_size_of_device_on_array(array, device_id)
            self.assertIsNone(size)

    def test_get_portgroup(self):
        array = self.data.array
        pg_name = self.data.port_group_name_f
        ref_pg = self.data.portgroup[0]
        portgroup = self.rest.get_portgroup(array, pg_name)
        self.assertEqual(ref_pg, portgroup)

    def test_get_port_ids(self):
        array = self.data.array
        pg_name = self.data.port_group_name_f
        ref_ports = ['FA-1D:4']
        port_ids = self.rest.get_port_ids(array, pg_name)
        self.assertEqual(ref_ports, port_ids)

    def test_get_port_ids_no_portgroup(self):
        array = self.data.array
        pg_name = self.data.port_group_name_f
        with mock.patch.object(self.rest, 'get_portgroup',
                               return_value=None):
            with self.assertRaisesRegex(
                    exception.VolumeBackendAPIException,
                    'Cannot find port group OS-fibre-PG.'):
                self.rest.get_port_ids(array, pg_name)

    def test_get_port(self):
        array = self.data.array
        port_id = 'FA-1D:4'
        ref_port = self.data.port_list[0]
        port = self.rest.get_port(array, port_id)
        self.assertEqual(ref_port, port)

    def test_get_iscsi_ip_address_and_iqn(self):
        array = self.data.array
        port_id = 'SE-4E:0'
        ref_ip = [self.data.ip]
        ref_iqn = self.data.initiator
        ip_addresses, iqn = self.rest.get_iscsi_ip_address_and_iqn(
            array, port_id)
        self.assertEqual(ref_ip, ip_addresses)
        self.assertEqual(ref_iqn, iqn)

    def test_get_iscsi_ip_address_and_iqn_no_port(self):
        array = self.data.array
        port_id = 'SE-4E:0'
        with mock.patch.object(self.rest, 'get_port', return_value=None):
            ip_addresses, iqn = self.rest.get_iscsi_ip_address_and_iqn(
                array, port_id)
            self.assertIsNone(ip_addresses)
            self.assertIsNone(iqn)

    def test_get_target_wwns(self):
        array = self.data.array
        pg_name = self.data.port_group_name_f
        ref_wwns = [self.data.wwnn1]
        target_wwns = self.rest.get_target_wwns(array, pg_name)
        self.assertEqual(ref_wwns, target_wwns)

    def test_get_target_wwns_failed(self):
        array = self.data.array
        pg_name = self.data.port_group_name_f
        with mock.patch.object(self.rest, 'get_port',
                               return_value=None):
            target_wwns = self.rest.get_target_wwns(array, pg_name)
            self.assertEqual([], target_wwns)

    def test_get_initiator_group(self):
        array = self.data.array
        ig_name = self.data.initiatorgroup_name_f
        ref_ig = self.data.inititiatorgroup[0]
        response_ig = self.rest.get_initiator_group(array, ig_name)
        self.assertEqual(ref_ig, response_ig)

    def test_get_initiator(self):
        array = self.data.array
        initiator_name = self.data.initiator
        ref_initiator = self.data.initiator_list[1]
        response_initiator = self.rest.get_initiator(array, initiator_name)
        self.assertEqual(ref_initiator, response_initiator)

    def test_get_initiator_list(self):
        array = self.data.array
        with mock.patch.object(self.rest, 'get_resource',
                               return_value={'initiatorId': '1234'}):
            init_list = self.rest.get_initiator_list(array)
            self.assertIsNotNone(init_list)

    def test_get_initiator_list_empty(self):
        array = self.data.array
        with mock.patch.object(self.rest, 'get_resource', return_value={}):
            init_list = self.rest.get_initiator_list(array)
            self.assertEqual([], init_list)

    def test_get_initiator_list_none(self):
        array = self.data.array
        with mock.patch.object(self.rest, 'get_resource', return_value=None):
            init_list = self.rest.get_initiator_list(array)
            self.assertIsNotNone(init_list)

    def test_get_initiator_group_from_initiator(self):
        initiator = self.data.wwpn1
        ref_group = self.data.initiatorgroup_name_f
        init_group = self.rest.get_initiator_group_from_initiator(
            self.data.array, initiator)
        self.assertEqual(ref_group, init_group)

    def test_get_initiator_group_from_initiator_failed(self):
        initiator = self.data.wwpn1
        with mock.patch.object(self.rest, 'get_initiator',
                               return_value=None):
            init_group = self.rest.get_initiator_group_from_initiator(
                self.data.array, initiator)
            self.assertIsNone(init_group)
        with mock.patch.object(self.rest, 'get_initiator',
                               return_value={'name': 'no_host'}):
            init_group = self.rest.get_initiator_group_from_initiator(
                self.data.array, initiator)
            self.assertIsNone(init_group)

    def test_create_initiator_group(self):
        init_group_name = self.data.initiatorgroup_name_f
        init_list = [self.data.wwpn1]
        extra_specs = self.data.extra_specs
        with mock.patch.object(
                self.rest, 'create_resource',
                return_value=(202, self.data.job_list[0])) as mock_create:
            payload = ({'executionOption': 'ASYNCHRONOUS',
                        'hostId': init_group_name, 'initiatorId': init_list})
            self.rest.create_initiator_group(
                self.data.array, init_group_name, init_list, extra_specs)
            mock_create.assert_called_once_with(
                self.data.array, 'sloprovisioning', 'host', payload)

    def test_delete_initiator_group(self):
        with mock.patch.object(self.rest, 'delete_resource') as mock_delete:
            self.rest.delete_initiator_group(
                self.data.array, self.data.initiatorgroup_name_f)
            mock_delete.assert_called_once_with(
                self.data.array, 'sloprovisioning', 'host',
                self.data.initiatorgroup_name_f)

    def test_get_masking_view(self):
        array = self.data.array
        masking_view_name = self.data.masking_view_name_f
        ref_mask_view = self.data.maskingview[0]
        masking_view = self.rest.get_masking_view(array, masking_view_name)
        self.assertEqual(ref_mask_view, masking_view)

    def test_get_masking_views_from_storage_group(self):
        array = self.data.array
        storagegroup_name = self.data.storagegroup_name_f
        ref_mask_view = [self.data.masking_view_name_f]
        masking_view = self.rest.get_masking_views_from_storage_group(
            array, storagegroup_name)
        self.assertEqual(ref_mask_view, masking_view)

    def test_get_masking_views_by_initiator_group(self):
        array = self.data.array
        initiatorgroup_name = self.data.initiatorgroup_name_f
        ref_mask_view = [self.data.masking_view_name_f]
        masking_view = self.rest.get_masking_views_by_initiator_group(
            array, initiatorgroup_name)
        self.assertEqual(ref_mask_view, masking_view)

    def test_get_masking_views_by_initiator_group_failed(self):
        array = self.data.array
        initiatorgroup_name = self.data.initiatorgroup_name_f
        with mock.patch.object(self.rest, 'get_initiator_group',
                               return_value=None):
            masking_view = self.rest.get_masking_views_by_initiator_group(
                array, initiatorgroup_name)
            self.assertEqual([], masking_view)
        with mock.patch.object(self.rest, 'get_initiator_group',
                               return_value={'name': 'no_mv'}):
            masking_view = self.rest.get_masking_views_by_initiator_group(
                array, initiatorgroup_name)
            self.assertEqual([], masking_view)

    def test_get_element_from_masking_view(self):
        array = self.data.array
        maskingview_name = self.data.masking_view_name_f
        # storage group
        ref_sg = self.data.storagegroup_name_f
        storagegroup = self.rest.get_element_from_masking_view(
            array, maskingview_name, storagegroup=True)
        self.assertEqual(ref_sg, storagegroup)
        # initiator group
        ref_ig = self.data.initiatorgroup_name_f
        initiatorgroup = self.rest.get_element_from_masking_view(
            array, maskingview_name, host=True)
        self.assertEqual(ref_ig, initiatorgroup)
        # portgroup
        ref_pg = self.data.port_group_name_f
        portgroup = self.rest.get_element_from_masking_view(
            array, maskingview_name, portgroup=True)
        self.assertEqual(ref_pg, portgroup)

    def test_get_element_from_masking_view_failed(self):
        array = self.data.array
        maskingview_name = self.data.masking_view_name_f
        # no element chosen
        element = self.rest.get_element_from_masking_view(
            array, maskingview_name)
        self.assertIsNone(element)
        # cannot retrieve maskingview
        with mock.patch.object(self.rest, 'get_masking_view',
                               return_value=None):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.rest.get_element_from_masking_view,
                              array, maskingview_name)

    def test_get_common_masking_views(self):
        array = self.data.array
        initiatorgroup = self.data.initiatorgroup_name_f
        portgroup = self.data.port_group_name_f
        ref_maskingview = self.data.masking_view_name_f
        maskingview_list = self.rest.get_common_masking_views(
            array, portgroup, initiatorgroup)
        self.assertEqual(ref_maskingview, maskingview_list)

    def test_get_common_masking_views_none(self):
        array = self.data.array
        initiatorgroup = self.data.initiatorgroup_name_f
        portgroup = self.data.port_group_name_f
        with mock.patch.object(self.rest, 'get_masking_view_list',
                               return_value=[]):
            maskingview_list = self.rest.get_common_masking_views(
                array, portgroup, initiatorgroup)
            self.assertEqual([], maskingview_list)

    def test_create_masking_view(self):
        maskingview_name = self.data.masking_view_name_f
        storagegroup_name = self.data.storagegroup_name_f
        port_group_name = self.data.port_group_name_f
        init_group_name = self.data.initiatorgroup_name_f
        extra_specs = self.data.extra_specs
        with mock.patch.object(
                self.rest, 'create_resource',
                return_value=(202, self.data.job_list[0])) as mock_create:
            payload = ({'executionOption': 'ASYNCHRONOUS',
                        'portGroupSelection': {
                            'useExistingPortGroupParam': {
                                'portGroupId': port_group_name}},
                        'maskingViewId': maskingview_name,
                        'hostOrHostGroupSelection': {
                            'useExistingHostParam': {
                                'hostId': init_group_name}},
                        'storageGroupSelection': {
                            'useExistingStorageGroupParam': {
                                'storageGroupId': storagegroup_name}}})
            self.rest.create_masking_view(
                self.data.array, maskingview_name, storagegroup_name,
                port_group_name, init_group_name, extra_specs)
            mock_create.assert_called_once_with(
                self.data.array, 'sloprovisioning', 'maskingview', payload)

    def test_delete_masking_view(self):
        with mock.patch.object(self.rest, 'delete_resource') as mock_delete:
            self.rest.delete_masking_view(
                self.data.array, self.data.masking_view_name_f)
            mock_delete.assert_called_once_with(
                self.data.array, 'sloprovisioning', 'maskingview',
                self.data.masking_view_name_f)

    def test_get_replication_capabilities(self):
        ref_response = self.data.capabilities['symmetrixCapability'][1]
        capabilities = self.rest.get_replication_capabilities(self.data.array)
        self.assertEqual(ref_response, capabilities)

    def test_is_clone_licenced(self):
        licence = self.rest.is_snapvx_licensed(self.data.array)
        self.assertTrue(licence)
        false_response = {'rdfCapable': True,
                          'snapVxCapable': False,
                          'symmetrixId': '000197800123'}
        with mock.patch.object(self.rest, 'get_replication_capabilities',
                               return_value=false_response):
            licence2 = self.rest.is_snapvx_licensed(self.data.array)
            self.assertFalse(licence2)

    def test_is_clone_licenced_error(self):
        with mock.patch.object(self.rest, 'get_replication_capabilities',
                               return_value=None):
            licence3 = self.rest.is_snapvx_licensed(self.data.array)
            self.assertFalse(licence3)

    def test_create_volume_snap(self):
        snap_name = self.data.volume_snap_vx[
            'snapshotSrcs'][0]['snapshotName']
        device_id = self.data.device_id
        extra_specs = self.data.extra_specs
        payload = {'deviceNameListSource': [{'name': device_id}],
                   'bothSides': 'false', 'star': 'false',
                   'force': 'false'}
        resource_type = 'snapshot/%(snap)s' % {'snap': snap_name}
        with mock.patch.object(
                self.rest, 'create_resource',
                return_value=(202, self.data.job_list[0])) as mock_create:
            self.rest.create_volume_snap(
                self.data.array, snap_name, device_id, extra_specs)
            mock_create.assert_called_once_with(
                self.data.array, 'replication', resource_type,
                payload, private='/private')
        ttl = 1
        payload = {'deviceNameListSource': [{'name': device_id}],
                   'bothSides': 'false', 'star': 'false',
                   'force': 'false', 'timeToLive': ttl,
                   'timeInHours': 'true'}
        with mock.patch.object(
                self.rest, 'create_resource',
                return_value=(202, self.data.job_list[0])) as mock_create:
            self.rest.create_volume_snap(
                self.data.array, snap_name, device_id, extra_specs, ttl)
            mock_create.assert_called_once_with(
                self.data.array, 'replication', resource_type,
                payload, private='/private')

    def test_modify_volume_snap(self):
        array = self.data.array
        source_id = self.data.device_id
        target_id = self.data.volume_snap_vx[
            'snapshotSrcs'][0]['linkedDevices'][0]['targetDevice']
        snap_name = self.data.volume_snap_vx['snapshotSrcs'][0]['snapshotName']
        extra_specs = self.data.extra_specs
        try:
            extra_specs.pop(utils.FORCE_VOL_EDIT)
        except KeyError:
            pass
        payload = {'deviceNameListSource': [{'name': source_id}],
                   'deviceNameListTarget': [
                       {'name': target_id}],
                   'copy': 'false', 'action': "",
                   'star': 'false', 'force': 'false',
                   'exact': 'false', 'remote': 'false',
                   'symforce': 'false', 'snap_id': self.data.snap_id}
        payload_restore = {'deviceNameListSource': [{'name': source_id}],
                           'deviceNameListTarget': [{'name': source_id}],
                           'action': 'Restore',
                           'star': 'false', 'force': 'false',
                           'snap_id': self.data.snap_id}
        with mock.patch.object(
                self.rest, 'modify_resource',
                return_value=(202, self.data.job_list[0])) as mock_modify:
            # link
            payload['action'] = 'Link'
            self.rest.modify_volume_snap(
                array, source_id, target_id, snap_name, extra_specs,
                self.data.snap_id, link=True)
            mock_modify.assert_called_once_with(
                array, 'replication', 'snapshot', payload,
                resource_name=snap_name, private='/private')
            # unlink
            mock_modify.reset_mock()
            payload['action'] = 'Unlink'
            self.rest.modify_volume_snap(
                array, source_id, target_id, snap_name, extra_specs,
                self.data.snap_id, unlink=True)
            mock_modify.assert_called_once_with(
                array, 'replication', 'snapshot', payload,
                resource_name=snap_name, private='/private')
            # restore
            mock_modify.reset_mock()
            payload['action'] = 'Restore'
            self.rest.modify_volume_snap(
                array, source_id, "", snap_name, extra_specs,
                self.data.snap_id, unlink=False, restore=True)
            mock_modify.assert_called_once_with(
                array, 'replication', 'snapshot', payload_restore,
                resource_name=snap_name, private='/private')
            # link or unlink, list of volumes
            mock_modify.reset_mock()
            payload['action'] = 'Link'
            self.rest.modify_volume_snap(
                array, "", "", snap_name, extra_specs, self.data.snap_id,
                unlink=False, link=True, list_volume_pairs=[(source_id,
                                                             target_id)])
            mock_modify.assert_called_once_with(
                array, 'replication', 'snapshot', payload,
                resource_name=snap_name, private='/private')
            # none selected
            mock_modify.reset_mock()
            self.rest.modify_volume_snap(
                array, source_id, target_id, snap_name, extra_specs,
                self.data.snap_id)
            mock_modify.assert_not_called()
            # copy mode is True
            payload['copy'] = 'true'
            self.rest.modify_volume_snap(
                array, source_id, target_id, snap_name, extra_specs,
                self.data.snap_id, link=True, copy=True)
            mock_modify.assert_called_once_with(
                array, 'replication', 'snapshot', payload,
                resource_name=snap_name, private='/private')

    def test_delete_volume_snap(self):
        array = self.data.array
        snap_name = self.data.volume_snap_vx['snapshotSrcs'][0]['snapshotName']
        source_device_id = self.data.device_id
        payload = {'deviceNameListSource': [{'name': source_device_id}],
                   'snap_id': self.data.snap_id}
        with mock.patch.object(self.rest, 'delete_resource') as mock_delete:
            self.rest.delete_volume_snap(
                array, snap_name, source_device_id, self.data.snap_id)
            mock_delete.assert_called_once_with(
                array, 'replication', 'snapshot', snap_name,
                payload=payload, private='/private')

    def test_delete_volume_snap_restore(self):
        array = self.data.array
        snap_name = self.data.volume_snap_vx['snapshotSrcs'][0]['snapshotName']
        source_device_id = self.data.device_id
        payload = {'deviceNameListSource': [{'name': source_device_id}],
                   'restore': True, 'snap_id': self.data.snap_id}
        with mock.patch.object(self.rest, 'delete_resource') as mock_delete:
            self.rest.delete_volume_snap(
                array, snap_name, source_device_id, self.data.snap_id,
                restored=True)
            mock_delete.assert_called_once_with(
                array, 'replication', 'snapshot', snap_name,
                payload=payload, private='/private')

    def test_get_volume_snap_info(self):
        array = self.data.array
        source_device_id = self.data.device_id
        ref_snap_info = self.data.volume_snap_vx
        snap_info = self.rest.get_volume_snap_info(array, source_device_id)
        self.assertEqual(ref_snap_info, snap_info)

    def test_get_volume_snap(self):
        array = self.data.array
        snap_id = self.data.snap_id
        snap_name = self.data.volume_snap_vx['snapshotSrcs'][0]['snapshotName']
        device_id = self.data.device_id
        ref_snap = self.data.volume_snap_vx['snapshotSrcs'][0]
        snap = self.rest.get_volume_snap(array, device_id, snap_name, snap_id)
        self.assertEqual(ref_snap, snap)

    def test_get_volume_snap_none(self):
        array = self.data.array
        snap_id = self.data.snap_id
        snap_name = self.data.volume_snap_vx['snapshotSrcs'][0]['snapshotName']
        device_id = self.data.device_id
        with mock.patch.object(self.rest, 'get_volume_snap_info',
                               return_value=None):
            snap = self.rest.get_volume_snap(
                array, device_id, snap_name, snap_id)
            self.assertIsNone(snap)
        with mock.patch.object(self.rest, 'get_volume_snap_info',
                               return_value={'snapshotSrcs': []}):
            snap = self.rest.get_volume_snap(
                array, device_id, snap_name, snap_id)
            self.assertIsNone(snap)

    def test_get_snap_linked_device_dict_list(self):
        array = self.data.array
        snap_name = 'temp-snapshot'
        device_id = self.data.device_id
        snap_list = [{'linked_vols': [
            {'target_device': device_id, 'state': 'Copied'}],
            'snap_name': snap_name, 'snapid': self.data.snap_id}]
        ref_snap_list = [{'snapid': self.data.snap_id, 'linked_vols': [
            {'state': 'Copied', 'target_device': '00001'}]}]
        with mock.patch.object(self.rest, '_find_snap_vx_source_sessions',
                               return_value=snap_list):
            snap_dict_list = self.rest._get_snap_linked_device_dict_list(
                array, device_id, snap_name)
            self.assertEqual(ref_snap_list, snap_dict_list)

    def test_get_sync_session(self):
        array = self.data.array
        source_id = self.data.device_id
        target_id = self.data.volume_snap_vx[
            'snapshotSrcs'][0]['linkedDevices'][0]['targetDevice']
        snap_name = self.data.volume_snap_vx['snapshotSrcs'][0]['snapshotName']
        ref_sync = self.data.volume_snap_vx[
            'snapshotSrcs'][0]['linkedDevices'][0]
        sync = self.rest.get_sync_session(
            array, source_id, snap_name, target_id, self.data.snap_id)
        self.assertEqual(ref_sync, sync)

    def test_find_snap_vx_sessions(self):
        array = self.data.array
        source_id = self.data.device_id
        ref_sessions = [{'snapid': self.data.snap_id,
                         'snap_name': 'temp-000AA-snapshot_for_clone',
                         'source_vol_id': self.data.device_id,
                         'target_vol_id': self.data.device_id2,
                         'expired': False, 'copy_mode': True,
                         'state': 'Copied'},
                        {'snapid': self.data.snap_id_2,
                         'snap_name': 'temp-000AA-snapshot_for_clone',
                         'source_vol_id': self.data.device_id,
                         'target_vol_id': self.data.device_id3,
                         'expired': False, 'copy_mode': True,
                         'state': 'Copied'}]

        with mock.patch.object(self.rest, 'get_volume_snap_info',
                               return_value=self.data.snapshot_src_details):
            src_list, __ = self.rest.find_snap_vx_sessions(array, source_id)
            self.assertEqual(ref_sessions, src_list)
            self.assertIsInstance(src_list, list)

    @mock.patch.object(rest.PowerMaxRest, '_get_private_volume',
                       return_value=tpd.PowerMaxData.snap_tgt_vol_details)
    @mock.patch.object(rest.PowerMaxRest, 'get_volume_snap_info',
                       return_value=tpd.PowerMaxData.snapshot_tgt_details)
    def test_find_snap_vx_sessions_tgt_only(self, mck_snap, mck_vol):
        array = self.data.array
        source_id = self.data.device_id
        ref_session = {'snapid': self.data.snap_id, 'state': 'Linked',
                       'copy_mode': False,
                       'snap_name': 'temp-000AA-snapshot_for_clone',
                       'source_vol_id': self.data.device_id2,
                       'target_vol_id': source_id, 'expired': True}

        __, snap_tgt = self.rest.find_snap_vx_sessions(
            array, source_id, tgt_only=True)
        self.assertEqual(ref_session, snap_tgt)
        self.assertIsInstance(snap_tgt, dict)

    def test_update_storagegroup_qos(self):
        sg_qos = {'srp': self.data.srp, 'num_of_vols': 2, 'cap_gb': 2,
                  'storageGroupId': 'OS-QOS-SG',
                  'slo': self.data.slo, 'workload': self.data.workload,
                  'hostIOLimit': {'host_io_limit_io_sec': '4000',
                                  'dynamicDistribution': 'Always',
                                  'host_io_limit_mb_sec': '4000'}}
        self.data.sg_details.append(sg_qos)
        array = self.data.array
        extra_specs = deepcopy(self.data.extra_specs)
        extra_specs['qos'] = {'total_iops_sec': '4000',
                              'DistributionType': 'Always'}
        return_value = self.rest.update_storagegroup_qos(
            array, 'OS-QOS-SG', extra_specs)
        self.assertEqual(False, return_value)
        extra_specs['qos'] = {'DistributionType': 'onFailure',
                              'total_bytes_sec': '419430400'}
        return_value = self.rest.update_storagegroup_qos(
            array, 'OS-QOS-SG', extra_specs)
        self.assertTrue(return_value)

    def test_update_storagegroup_qos_exception(self):
        array = self.data.array
        storage_group = self.data.defaultstoragegroup_name
        extra_specs = deepcopy(self.data.extra_specs)
        extra_specs['qos'] = {'total_iops_sec': '4000',
                              'DistributionType': 'Wrong',
                              'total_bytes_sec': '4194304000'}
        with mock.patch.object(self.rest, 'check_status_code_success',
                               side_effect=[None, None, None, Exception]):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.rest.update_storagegroup_qos, array,
                              storage_group, extra_specs)
            extra_specs['qos']['DistributionType'] = 'Always'
            return_value = self.rest.update_storagegroup_qos(
                array, 'OS-QOS-SG', extra_specs)
            self.assertFalse(return_value)

    @mock.patch.object(rest.PowerMaxRest, 'modify_storage_group',
                       return_value=(202, tpd.PowerMaxData.job_list[0]))
    def test_set_storagegroup_srp(self, mock_mod):
        self.rest.set_storagegroup_srp(
            self.data.array, self.data.test_vol_grp_name,
            self.data.srp, self.data.extra_specs)
        mock_mod.assert_called_once()

    def test_get_rdf_group(self):
        with mock.patch.object(self.rest, 'get_resource') as mock_get:
            self.rest.get_rdf_group(self.data.array, self.data.rdf_group_no_1)
            mock_get.assert_called_once_with(
                self.data.array, 'replication', 'rdf_group',
                self.data.rdf_group_no_1)

    def test_get_rdf_group_list(self):
        rdf_list = self.rest.get_rdf_group_list(self.data.array)
        self.assertEqual(self.data.rdf_group_list, rdf_list)

    def test_get_rdf_group_volume(self):
        vol_details = self.data.private_vol_details['resultList']['result'][0]
        with mock.patch.object(self.rest, '_get_private_volume',
                               return_value=vol_details) as mock_get:
            self.rest.get_rdf_group_volume(
                self.data.array, self.data.device_id)
            mock_get.assert_called_once_with(
                self.data.array, self.data.device_id)

    def test_are_vols_rdf_paired(self):
        are_vols1, local_state, pair_state = self.rest.are_vols_rdf_paired(
            self.data.array, self.data.remote_array, self.data.device_id,
            self.data.device_id2)
        self.assertTrue(are_vols1)
        are_vols2, local_state, pair_state = self.rest.are_vols_rdf_paired(
            self.data.array, '00012345', self.data.device_id,
            self.data.device_id2)
        self.assertFalse(are_vols2)
        with mock.patch.object(self.rest, 'get_rdf_group_volume',
                               return_value=None):
            are_vols3, local, pair = self.rest.are_vols_rdf_paired(
                self.data.array, self.data.remote_array, self.data.device_id,
                self.data.device_id2)
            self.assertFalse(are_vols3)

    def test_get_rdf_group_number(self):
        rdfg_num = self.rest.get_rdf_group_number(
            self.data.array, self.data.rdf_group_name_1)
        self.assertEqual(self.data.rdf_group_no_1, rdfg_num)
        with mock.patch.object(self.rest, 'get_rdf_group_list',
                               return_value=None):
            rdfg_num2 = self.rest.get_rdf_group_number(
                self.data.array, self.data.rdf_group_name_1)
            self.assertIsNone(rdfg_num2)
        with mock.patch.object(self.rest, 'get_rdf_group',
                               return_value=None):
            rdfg_num3 = self.rest.get_rdf_group_number(
                self.data.array, self.data.rdf_group_name_1)
            self.assertIsNone(rdfg_num3)

    @mock.patch.object(rest.PowerMaxRest, 'get_rdf_group',
                       side_effect=[{'numDevices': 0}, {'numDevices': 0},
                                    {'numDevices': 1}, {'numDevices': 1}])
    def test_get_metro_payload_info(self, mock_rdfg):
        payload_in = {'establish': 'true', 'rdfMode': 'Active',
                      'rdfType': 'RDF1'}

        # First volume out, Metro use bias not set
        act_payload_1 = self.rest.get_metro_payload_info(
            self.data.array, payload_in.copy(), self.data.rdf_group_no_1, {},
            True)
        self.assertEqual(payload_in, act_payload_1)

        # First volume out, Metro use bias set
        act_payload_2 = self.rest.get_metro_payload_info(
            self.data.array, payload_in.copy(), self.data.rdf_group_no_1,
            {'metro_bias': True}, True)
        self.assertEqual('true', act_payload_2['metroBias'])

        # Not first vol in RDFG, consistency exempt not set
        act_payload_3 = self.rest.get_metro_payload_info(
            self.data.array, payload_in.copy(), self.data.rdf_group_no_1,
            {'exempt': False}, False)
        ref_payload_3 = {'rdfMode': 'Active', 'rdfType': 'RDF1'}
        self.assertEqual(ref_payload_3, act_payload_3)

        # Not first vol in RDFG, consistency exempt set
        act_payload_4 = self.rest.get_metro_payload_info(
            self.data.array, payload_in.copy(), self.data.rdf_group_no_1,
            {'exempt': True}, True)
        ref_payload_4 = {'rdfType': 'RDF1', 'exempt': 'true',
                         'rdfMode': 'Active'}
        self.assertEqual(ref_payload_4, act_payload_4)

    def test_get_storage_group_rep(self):
        array = self.data.array
        source_group_name = self.data.storagegroup_name_source
        ref_details = self.data.sg_details_rep[0]
        volume_group = self.rest.get_storage_group_rep(array,
                                                       source_group_name)
        self.assertEqual(volume_group, ref_details)

    def test_get_volumes_in_storage_group(self):
        array = self.data.array
        storagegroup_name = self.data.storagegroup_name_source
        ref_volumes = [self.data.device_id, self.data.device_id2]
        volume_list = self.rest.get_volumes_in_storage_group(
            array, storagegroup_name)
        self.assertEqual(ref_volumes, volume_list)

    def test_create_storagegroup_snap(self):
        array = self.data.array
        extra_specs = self.data.extra_specs
        source_group = self.data.storagegroup_name_source
        snap_name = self.data.group_snapshot_name
        with mock.patch.object(
                self.rest, 'create_storagegroup_snap') as mock_create:
            self.rest.create_storagegroup_snap(
                array, source_group, snap_name, extra_specs)
            mock_create.assert_called_once_with(
                array, source_group, snap_name, extra_specs)

    def test_delete_storagegroup_snap(self):
        array = self.data.array
        source_group = self.data.storagegroup_name_source
        snap_name = self.data.group_snapshot_name
        with mock.patch.object(
                self.rest, 'delete_storagegroup_snap') as mock_delete:
            self.rest.delete_storagegroup_snap(
                array, source_group, snap_name, '0')
            mock_delete.assert_called_once_with(
                array, source_group, snap_name, '0')

    @mock.patch.object(rest.PowerMaxRest, 'get_resource',
                       return_value={'snapids': [tpd.PowerMaxData.snap_id,
                                                 tpd.PowerMaxData.snap_id_2]})
    def test_get_storagegroup_snap_id_list(self, mock_list):
        array = self.data.array
        source_group = self.data.storagegroup_name_source
        snap_name = self.data.group_snapshot_name
        ret_list = self.rest.get_storage_group_snap_id_list(
            array, source_group, snap_name)
        self.assertEqual([self.data.snap_id, self.data.snap_id_2], ret_list)

    def test_get_storagegroup_rdf_details(self):
        details = self.rest.get_storagegroup_rdf_details(
            self.data.array, self.data.test_vol_grp_name,
            self.data.rdf_group_no_1)
        self.assertEqual(self.data.sg_rdf_details[0], details)

    def test_verify_rdf_state(self):
        verify1 = self.rest._verify_rdf_state(
            self.data.array, self.data.test_vol_grp_name,
            self.data.rdf_group_no_1, 'Failover')
        self.assertTrue(verify1)
        verify2 = self.rest._verify_rdf_state(
            self.data.array, self.data.test_fo_vol_group,
            self.data.rdf_group_no_1, 'Establish')
        self.assertTrue(verify2)

    def test_delete_storagegroup_rdf(self):
        with mock.patch.object(
                self.rest, 'delete_resource') as mock_del:
            self.rest.delete_storagegroup_rdf(
                self.data.array, self.data.test_vol_grp_name,
                self.data.rdf_group_no_1)
            mock_del.assert_called_once()

    def test_is_next_gen_array(self):
        is_next_gen = self.rest.is_next_gen_array(self.data.array)
        self.assertFalse(is_next_gen)
        is_next_gen2 = self.rest.is_next_gen_array(self.data.array_herc)
        self.assertTrue(is_next_gen2)

    def test_get_array_model_info(self):
        array_model_vmax, is_next_gen = self.rest.get_array_model_info(
            self.data.array)
        self.assertEqual('VMAX250F', array_model_vmax)
        self.assertFalse(is_next_gen)
        array_model_powermax, is_next_gen2 = self.rest.get_array_model_info(
            self.data.array_herc)
        self.assertTrue(is_next_gen2)
        self.assertEqual('PowerMax 2000', array_model_powermax)

    @mock.patch.object(rest.PowerMaxRest, 'modify_resource',
                       return_value=('200', 'JobComplete'))
    def test_modify_volume_snap_rename(self, mock_modify):
        array = self.data.array
        source_id = self.data.device_id
        old_snap_backend_name = self.data.snapshot_id
        new_snap_backend_name = self.data.managed_snap_id
        self.rest.modify_volume_snap(
            array, source_id, source_id, old_snap_backend_name,
            self.data.extra_specs, self.data.snap_id, link=False,
            unlink=False, rename=True, new_snap_name=new_snap_backend_name)
        mock_modify.assert_called_once()

    def test_get_private_volume_list_pass(self):
        array_id = self.data.array
        response = {'count': 1,
                    'expirationTime': 1521650650793,
                    'id': 'f3aab01c-a5a8-4fb4-af2b-16ae1c46dc9e_0',
                    'maxPageSize': 1000,
                    'resultList': {'from': 1,
                                   'result': [{'volumeHeader': {
                                       'capGB': 1.0,
                                       'capMB': 1026.0,
                                       'volumeId': '00001',
                                       'status': 'Ready',
                                       'configuration': 'TDEV'}}],
                                   'to': 1}}

        with mock.patch.object(
                self.rest, 'get_resource',
                return_value=self.data.p_vol_rest_response_single):
            volume = self.rest.get_private_volume_list(array_id)
            self.assertEqual(response, volume)

    def test_get_private_volume_list_none(self):
        array_id = self.data.array
        response = []
        with mock.patch.object(
                self.rest, 'request',
                return_value=(
                    200, tpd.PowerMaxData.p_vol_rest_response_none)):
            vol_list = self.rest.get_private_volume_list(array_id)
            self.assertEqual(response, vol_list)

    @mock.patch.object(
        rest.PowerMaxRest, 'get_iterator_page_list',
        return_value=(tpd.PowerMaxData.p_vol_rest_response_iterator_2[
            'result']))
    def test_get_private_volume_list_iterator(self, mock_iterator):
        array_id = self.data.array
        response = [
            {'volumeHeader': {
                'capGB': 1.0, 'capMB': 1026.0, 'volumeId': '00002',
                'status': 'Ready', 'configuration': 'TDEV'}},
            {'volumeHeader': {
                'capGB': 1.0, 'capMB': 1026.0, 'volumeId': '00001',
                'status': 'Ready', 'configuration': 'TDEV'}}]
        with mock.patch.object(
                self.rest, 'request', return_value=(200, deepcopy(
                    self.data.p_vol_rest_response_iterator_1))):
            volume = self.rest.get_private_volume_list(array_id)
        self.assertEqual(response, volume)

    @mock.patch.object(rest.PowerMaxRest, 'get_resource')
    def test_get_private_volume_list_params_dict_input(self, mck_get):
        array_id = self.data.array
        input_param = {'unit-test': True}
        ref = {'unit-test': True,
               'expiration_time_mins': rest.ITERATOR_EXPIRATION}

        self.rest.get_private_volume_list(array_id, input_param)
        mck_get.assert_called_once_with(
            self.data.array, rest.SLOPROVISIONING, 'volume', params=ref,
            private='/private')

    @mock.patch.object(rest.PowerMaxRest, 'get_resource')
    def test_get_private_volume_list_params_str_input(self, mck_get):
        array_id = self.data.array
        input_param = '&unit-test=True'
        ref = '&unit-test=True&expiration_time_mins=%(expire)s' % {
            'expire': rest.ITERATOR_EXPIRATION}

        self.rest.get_private_volume_list(array_id, input_param)
        mck_get.assert_called_once_with(
            self.data.array, rest.SLOPROVISIONING, 'volume', params=ref,
            private='/private')

    @mock.patch.object(rest.PowerMaxRest, 'get_resource')
    def test_get_private_volume_list_params_no_input(self, mck_get):
        array_id = self.data.array
        ref = {'expiration_time_mins': rest.ITERATOR_EXPIRATION}

        self.rest.get_private_volume_list(array_id)
        mck_get.assert_called_once_with(
            self.data.array, rest.SLOPROVISIONING, 'volume', params=ref,
            private='/private')

    @mock.patch.object(rest.PowerMaxRest, '_delete_iterator')
    def test_get_iterator_list(self, mck_del):
        with mock.patch.object(
                self.rest, 'get_request', side_effect=[
                    self.data.rest_iterator_resonse_one,
                    self.data.rest_iterator_resonse_two]):
            expected_response = [
                {'volumeHeader': {
                    'capGB': 1.0, 'capMB': 1026.0, 'volumeId': '00001',
                    'status': 'Ready', 'configuration': 'TDEV'}},
                {'volumeHeader': {
                    'capGB': 1.0, 'capMB': 1026.0, 'volumeId': '00002',
                    'status': 'Ready', 'configuration': 'TDEV'}}]
            iterator_id = 'test_iterator_id'
            result_count = 1500
            start_position = 1
            end_position = 1000
            max_page_size = 1000

            actual_response = self.rest.get_iterator_page_list(
                iterator_id, result_count, start_position, end_position,
                max_page_size)
            mck_del.assert_called_once_with(iterator_id)
            self.assertEqual(expected_response, actual_response)

    @mock.patch.object(rest.PowerMaxRest, 'request',
                       return_value=(204, 'Deleted Iterator'))
    def test_delete_iterator(self, mck_del):
        iterator_id = 'test_iterator_id'
        self.rest._delete_iterator(iterator_id)
        mck_del.assert_called_once_with(
            '/common/Iterator/%(iter)s' % {'iter': iterator_id},
            rest.DELETE)

    def test_set_rest_credentials(self):
        array_info = {
            'RestServerIp': '10.10.10.10',
            'RestServerPort': '8443',
            'RestUserName': 'user_test',
            'RestPassword': 'pass_test',
            'SerialNumber': self.data.array,
            'SSLVerify': True,
        }
        self.rest.set_rest_credentials(array_info)
        self.assertEqual('user_test', self.rest.user)
        self.assertEqual('pass_test', self.rest.passwd)
        self.assertTrue(self.rest.verify)
        self.assertEqual('https://10.10.10.10:8443/univmax/restapi',
                         self.rest.base_uri)

    @mock.patch.object(
        rest.PowerMaxRest, 'get_iterator_page_list', return_value=(
            tpd.PowerMaxData.p_vol_rest_response_iterator_2[
                'result']))
    def test_list_pagination(self, mock_iter):
        result_list = self.rest.list_pagination(
            deepcopy(self.data.p_vol_rest_response_iterator_1))
        # reflects sample data, 1 from first iterator page and 1 from
        # second iterator page
        self.assertTrue(2 == len(result_list))

    def test_get_vmax_model(self):
        reference = 'PowerMax_2000'
        with mock.patch.object(self.rest, 'get_request',
                               return_value=self.data.powermax_model_details):
            self.assertEqual(self.rest.get_vmax_model(self.data.array),
                             reference)

    def test_set_u4p_failover_config(self):
        self.rest.set_u4p_failover_config(self.data.u4p_failover_config)

        self.assertTrue(self.rest.u4p_failover_enabled)
        self.assertEqual('3', self.rest.u4p_failover_retries)
        self.assertEqual('10', self.rest.u4p_failover_timeout)
        self.assertEqual('2', self.rest.u4p_failover_backoff_factor)
        self.assertEqual('10.10.10.10', self.rest.primary_u4p)
        self.assertEqual('10.10.10.11',
                         self.rest.u4p_failover_targets[0]['san_ip'])
        self.assertEqual('10.10.10.12',
                         self.rest.u4p_failover_targets[1]['san_ip'])

    def test_handle_u4p_failover_with_targets(self):
        self.rest.u4p_failover_targets = self.data.u4p_failover_target
        self.rest._handle_u4p_failover()

        self.assertTrue(self.rest.u4p_in_failover)
        self.assertEqual('test', self.rest.user)
        self.assertEqual('test', self.rest.passwd)
        self.assertEqual('/path/to/cert', self.rest.verify)
        self.assertEqual('https://10.10.10.11:8443/univmax/restapi',
                         self.rest.base_uri)

    def test_handle_u4p_failover_no_targets_exception(self):
        self.rest.u4p_failover_targets = []
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.rest._handle_u4p_failover)

    @mock.patch.object(rest.PowerMaxRest, 'get_array_detail',
                       return_value=tpd.PowerMaxData.powermax_model_details)
    def test_get_array_ucode(self, mck_ucode):
        array = self.data.array
        ucode = self.rest.get_array_ucode_version(array)
        self.assertEqual(self.data.powermax_model_details['ucode'], ucode)

    def test_validate_unisphere_version_suceess(self):
        version = tpd.PowerMaxData.unisphere_version
        returned_version = {'version': version}
        with mock.patch.object(self.rest, "request",
                               return_value=(200,
                                             returned_version)) as mock_req:
            valid_version = self.rest.validate_unisphere_version()
            self.assertTrue(valid_version)
        request_count = mock_req.call_count
        self.assertEqual(1, request_count)

    def test_validate_unisphere_version_fail(self):
        version = tpd.PowerMaxData.unisphere_version_90
        returned_version = {'version': version}

        with mock.patch.object(self.rest, "request",
                               return_value=(200,
                                             returned_version))as mock_req:
            valid_version = self.rest.validate_unisphere_version()
            self.assertFalse(valid_version)
        request_count = mock_req.call_count
        self.assertEqual(1, request_count)

    def test_validate_unisphere_version_no_connection(self):
        with mock.patch.object(self.rest, "request",
                               return_value=(500, '')) as mock_req:
            valid_version = self.rest.validate_unisphere_version()
            self.assertFalse(valid_version)
        request_count = mock_req.call_count
        self.assertEqual(2, request_count)

    @mock.patch.object(rest.PowerMaxRest, 'get_resource',
                       return_value=tpd.PowerMaxData.sg_rdf_group_details)
    def test_get_storage_group_rdf_group_state(self, mck_get):
        ref_get_resource = ('storagegroup/%(sg)s/rdf_group/%(rdfg)s' % {
            'sg': self.data.test_vol_grp_name,
            'rdfg': self.data.rdf_group_no_1})
        states = self.rest.get_storage_group_rdf_group_state(
            self.data.array, self.data.test_vol_grp_name,
            self.data.rdf_group_no_1)
        mck_get.assert_called_once_with(
            self.data.array, 'replication', ref_get_resource)
        self.assertEqual(states, [utils.RDF_SUSPENDED_STATE])

    @mock.patch.object(rest.PowerMaxRest, 'get_resource',
                       return_value={'rdfgs': [100, 200]})
    def test_get_storage_group_rdf_groups(self, mck_get):
        rdf_groups = self.rest.get_storage_group_rdf_groups(
            self.data.array, self.data.storagegroup_name_f)
        self.assertEqual([100, 200], rdf_groups)

    @mock.patch.object(rest.PowerMaxRest, 'get_resource',
                       return_value={"name": ["00038", "00039"]})
    def test_get_rdf_group_volume_list(self, mck_get):
        volumes_list = self.rest.get_rdf_group_volume_list(
            self.data.array, self.data.rdf_group_no_1)
        self.assertEqual(["00038", "00039"], volumes_list)

    @mock.patch.object(rest.PowerMaxRest, 'get_resource')
    def test_get_rdf_pair_volume(self, mck_get):
        rdf_grp_no = self.data.rdf_group_no_1
        device_id = self.data.device_id
        array = self.data.array
        ref_get_resource = ('rdf_group/%(rdf_group)s/volume/%(device)s' % {
            'rdf_group': rdf_grp_no, 'device': device_id})
        self.rest.get_rdf_pair_volume(array, rdf_grp_no, device_id)
        mck_get.assert_called_once_with(array, 'replication', ref_get_resource)

    @mock.patch.object(rest.PowerMaxRest, 'wait_for_job')
    @mock.patch.object(rest.PowerMaxRest, 'create_resource',
                       return_value=(200, 'job'))
    def test_srdf_protect_storage_group(self, mck_create, mck_wait):
        array_id = self.data.array
        remote_array_id = self.data.remote_array
        rdf_group_no = self.data.rdf_group_no_1
        replication_mode = utils.REP_METRO
        sg_name = self.data.default_sg_re_enabled
        service_level = 'Diamond'
        extra_specs = deepcopy(self.data.rep_extra_specs)
        extra_specs[utils.METROBIAS] = True
        remote_sg = self.data.rdf_managed_async_grp

        ref_payload = {
            'executionOption': 'ASYNCHRONOUS', 'metroBias': 'true',
            'replicationMode': 'Active', 'remoteSLO': service_level,
            'remoteSymmId': remote_array_id, 'rdfgNumber': rdf_group_no,
            'remoteStorageGroupName': remote_sg, 'establish': 'true'}
        ref_resource = ('storagegroup/%(sg_name)s/rdf_group' %
                        {'sg_name': sg_name})

        self.rest.srdf_protect_storage_group(
            array_id, remote_array_id, rdf_group_no, replication_mode,
            sg_name, service_level, extra_specs, target_sg=remote_sg)
        mck_create.assert_called_once_with(
            array_id, 'replication', ref_resource, ref_payload)

    @mock.patch.object(rest.PowerMaxRest, 'wait_for_job')
    @mock.patch.object(rest.PowerMaxRest, 'modify_resource',
                       return_value=(200, 'job'))
    def test_srdf_modify_group(self, mck_modify, mck_wait):
        array_id = self.data.array
        rdf_group_no = self.data.rdf_group_no_1
        sg_name = self.data.default_sg_re_enabled
        payload = {'executionOption': 'ASYNCHRONOUS', 'action': 'Suspend'}
        extra_specs = self.data.rep_extra_specs
        msg = 'test'
        resource = ('storagegroup/%(sg_name)s/rdf_group/%(rdf_group_no)s' % {
            'sg_name': sg_name, 'rdf_group_no': rdf_group_no})

        self.rest.srdf_modify_group(
            array_id, rdf_group_no, sg_name, payload, extra_specs, msg)
        mck_modify.assert_called_once_with(
            array_id, 'replication', resource, payload)
        mck_wait.assert_called_once_with(msg, 200, 'job', extra_specs)

    @mock.patch.object(rest.PowerMaxRest, 'wait_for_job')
    @mock.patch.object(rest.PowerMaxRest, 'modify_resource',
                       return_value=(200, 'job'))
    def test_srdf_modify_group_async_call_false(self, mck_modify, mck_wait):
        array_id = self.data.array
        rdf_group_no = self.data.rdf_group_no_1
        sg_name = self.data.default_sg_re_enabled
        payload = {'action': 'Suspend'}
        extra_specs = self.data.rep_extra_specs
        msg = 'test'
        resource = ('storagegroup/%(sg_name)s/rdf_group/%(rdf_group_no)s' % {
            'sg_name': sg_name, 'rdf_group_no': rdf_group_no})

        self.rest.srdf_modify_group(
            array_id, rdf_group_no, sg_name, payload, extra_specs, msg, False)
        mck_modify.assert_called_once_with(
            array_id, 'replication', resource, payload)
        mck_wait.assert_not_called()

    @mock.patch.object(rest.PowerMaxRest, 'srdf_modify_group')
    @mock.patch.object(rest.PowerMaxRest, 'get_storage_group_rdf_group_state',
                       return_value=[utils.RDF_CONSISTENT_STATE])
    def test_srdf_suspend_replication(self, mck_get, mck_modify):
        array_id = self.data.array
        rdf_group_no = self.data.rdf_group_no_1
        sg_name = self.data.default_sg_re_enabled
        rep_extra_specs = self.data.rep_extra_specs

        self.rest.srdf_suspend_replication(
            array_id, sg_name, rdf_group_no, rep_extra_specs)
        mck_modify.assert_called_once_with(
            array_id, rdf_group_no, sg_name,
            {'suspend': {'force': 'true'}, 'action': 'Suspend'},
            rep_extra_specs, 'Suspend SRDF Group Replication')

    @mock.patch.object(rest.PowerMaxRest, 'srdf_modify_group')
    @mock.patch.object(rest.PowerMaxRest, 'get_storage_group_rdf_group_state',
                       return_value=[utils.RDF_SUSPENDED_STATE,
                                     utils.RDF_CONSISTENT_STATE])
    def test_srdf_suspend_replication_dual_states(self, mck_get, mck_modify):
        array_id = self.data.array
        rdf_group_no = self.data.rdf_group_no_1
        sg_name = self.data.default_sg_re_enabled
        rep_extra_specs = self.data.rep_extra_specs

        self.rest.srdf_suspend_replication(
            array_id, sg_name, rdf_group_no, rep_extra_specs)
        mck_modify.assert_called_once_with(
            array_id, rdf_group_no, sg_name,
            {'suspend': {'force': 'true'}, 'action': 'Suspend'},
            rep_extra_specs, 'Suspend SRDF Group Replication')

    @mock.patch.object(rest.PowerMaxRest, 'srdf_modify_group')
    @mock.patch.object(rest.PowerMaxRest, 'get_storage_group_rdf_group_state',
                       return_value=[utils.RDF_SUSPENDED_STATE])
    def test_srdf_suspend_replication_already_suspended(self, mck_get,
                                                        mck_modify):
        array_id = self.data.array
        rdf_group_no = self.data.rdf_group_no_1
        sg_name = self.data.default_sg_re_enabled
        rep_extra_specs = self.data.rep_extra_specs

        self.rest.srdf_suspend_replication(
            array_id, sg_name, rdf_group_no, rep_extra_specs)
        mck_modify.assert_not_called()

    @mock.patch.object(rest.PowerMaxRest, 'srdf_modify_group')
    @mock.patch.object(rest.PowerMaxRest, 'get_storage_group_rdf_group_state',
                       return_value=[utils.RDF_SUSPENDED_STATE])
    def test_srdf_resume_replication(self, mck_get, mck_modify):
        array_id = self.data.array
        rdf_group_no = self.data.rdf_group_no_1
        sg_name = self.data.default_sg_re_enabled
        rep_extra_specs = self.data.rep_extra_specs
        rep_extra_specs[utils.REP_CONFIG] = self.data.rep_config_async
        rep_extra_specs[utils.REP_MODE] = utils.REP_ASYNC

        self.rest.srdf_resume_replication(
            array_id, sg_name, rdf_group_no, rep_extra_specs)
        mck_modify.assert_called_once_with(
            array_id, rdf_group_no, sg_name, {'action': 'Resume'},
            rep_extra_specs, 'Resume SRDF Group Replication', True)

    @mock.patch.object(rest.PowerMaxRest, 'srdf_modify_group')
    @mock.patch.object(rest.PowerMaxRest, 'get_storage_group_rdf_group_state',
                       return_value=[utils.RDF_SUSPENDED_STATE])
    def test_srdf_resume_replication_metro(self, mck_get, mck_modify):
        array_id = self.data.array
        rdf_group_no = self.data.rdf_group_no_1
        sg_name = self.data.default_sg_re_enabled
        rep_extra_specs = deepcopy(self.data.rep_extra_specs_metro)
        rep_extra_specs[utils.REP_MODE] = utils.REP_METRO

        self.rest.srdf_resume_replication(
            array_id, sg_name, rdf_group_no, rep_extra_specs)
        mck_modify.assert_called_once_with(
            array_id, rdf_group_no, sg_name,
            {"action": "Establish", "establish": {"metroBias": "true"}},
            rep_extra_specs, 'Resume SRDF Group Replication', True)

    @mock.patch.object(rest.PowerMaxRest, 'srdf_modify_group')
    @mock.patch.object(rest.PowerMaxRest, 'get_storage_group_rdf_group_state',
                       return_value=[utils.RDF_CONSISTENT_STATE])
    def test_srdf_resume_replication_already_resumed(self, mck_get,
                                                     mck_modify):
        array_id = self.data.array
        rdf_group_no = self.data.rdf_group_no_1
        sg_name = self.data.default_sg_re_enabled
        rep_extra_specs = self.data.rep_extra_specs

        self.rest.srdf_resume_replication(
            array_id, sg_name, rdf_group_no, rep_extra_specs)
        mck_modify.assert_not_called()

    @mock.patch.object(rest.PowerMaxRest, 'srdf_modify_group')
    @mock.patch.object(rest.PowerMaxRest, 'get_storage_group_rdf_group_state',
                       return_value=[utils.RDF_CONSISTENT_STATE])
    def test_srdf_establish_replication(self, mck_get, mck_modify):
        array_id = self.data.array
        rdf_group_no = self.data.rdf_group_no_1
        sg_name = self.data.default_sg_re_enabled
        rep_extra_specs = self.data.rep_extra_specs

        first_call = call(array_id, rdf_group_no, sg_name,
                          {'action': 'Suspend'}, rep_extra_specs,
                          'Suspend SRDF Group Replication')
        second_call = call(array_id, rdf_group_no, sg_name,
                           {'action': 'Establish'}, rep_extra_specs,
                           'Incremental Establish SRDF Group Replication')

        self.rest.srdf_establish_replication(
            array_id, sg_name, rdf_group_no, rep_extra_specs)
        mck_modify.assert_has_calls([first_call, second_call], any_order=False)

    @mock.patch.object(rest.PowerMaxRest, 'srdf_modify_group')
    def test_srdf_failover_group(self, mck_modify):
        array_id = self.data.array
        rdf_group_no = self.data.rdf_group_no_1
        sg_name = self.data.default_sg_re_enabled
        rep_extra_specs = self.data.rep_extra_specs

        self.rest.srdf_failover_group(
            array_id, sg_name, rdf_group_no, rep_extra_specs)
        mck_modify.assert_called_once_with(
            array_id, rdf_group_no, sg_name, {'action': 'Failover'},
            rep_extra_specs, 'Failing over SRDF group replication')

    @mock.patch.object(rest.PowerMaxRest, 'srdf_modify_group')
    def test_srdf_failback_group(self, mck_modify):
        array_id = self.data.array
        rdf_group_no = self.data.rdf_group_no_1
        sg_name = self.data.default_sg_re_enabled
        rep_extra_specs = self.data.rep_extra_specs

        self.rest.srdf_failback_group(
            array_id, sg_name, rdf_group_no, rep_extra_specs)
        mck_modify.assert_called_once_with(
            array_id, rdf_group_no, sg_name, {'action': 'Failback'},
            rep_extra_specs, 'Failing back SRDF group replication')

    @mock.patch.object(rest.PowerMaxRest, 'wait_for_job')
    @mock.patch.object(rest.PowerMaxRest, 'modify_storage_group',
                       return_value=(200, 'job'))
    def test_srdf_remove_device_pair_from_storage_group(self, mck_modify,
                                                        mck_wait):
        array_id = self.data.array
        sg_name = self.data.default_sg_re_enabled
        remote_array_id = self.data.remote_array
        device_id = self.data.device_id
        rep_extra_specs = self.data.rep_extra_specs
        ref_payload = {
            'editStorageGroupActionParam': {
                'removeVolumeParam': {
                    'volumeId': [device_id],
                    'remoteSymmSGInfoParam': {
                        'remote_symmetrix_1_id': remote_array_id,
                        'remote_symmetrix_1_sgs': [sg_name]}}}}

        self.rest.srdf_remove_device_pair_from_storage_group(
            array_id, sg_name, remote_array_id, device_id, rep_extra_specs)
        mck_modify.assert_called_once_with(
            array_id, sg_name, ref_payload)

    @mock.patch.object(rest.PowerMaxRest, 'delete_resource')
    def test_srdf_delete_device_pair(self, mck_del):
        array_id = self.data.array
        rdf_group_no = self.data.rdf_group_no_1
        device_id = self.data.device_id
        ref_resource = ('%(rdfg)s/volume/%(dev)s' % {
            'rdfg': rdf_group_no, 'dev': device_id})

        self.rest.srdf_delete_device_pair(
            array_id, rdf_group_no, device_id)
        mck_del.assert_called_once_with(
            array_id, 'replication', 'rdf_group', ref_resource)

    @mock.patch.object(
        rest.PowerMaxRest, 'get_rdf_pair_volume',
        return_value=tpd.PowerMaxData.rdf_group_vol_details)
    @mock.patch.object(rest.PowerMaxRest, 'wait_for_job')
    @mock.patch.object(rest.PowerMaxRest, 'create_resource',
                       return_value=(200, 'job'))
    def test_srdf_create_device_pair_async(
            self, mck_create, mck_wait, mck_get):
        array_id = self.data.array
        remote_array = self.data.remote_array
        rdf_group_no = self.data.rdf_group_no_1
        mode = utils.REP_ASYNC
        device_id = self.data.device_id
        tgt_device_id = self.data.device_id2
        rep_extra_specs = self.data.rep_extra_specs
        rep_extra_specs['array'] = remote_array

        ref_payload = {
            'executionOption': 'ASYNCHRONOUS', 'rdfMode': mode,
            'localDeviceListCriteriaParam': {'localDeviceList': [device_id]},
            'rdfType': 'RDF1', 'invalidateR2': 'true', 'exempt': 'true'}
        ref_resource = 'rdf_group/%(rdfg)s/volume' % {'rdfg': rdf_group_no}
        ref_response = {
            'array': array_id, 'remote_array': remote_array,
            'src_device': device_id, 'tgt_device': tgt_device_id,
            'session_info': self.data.rdf_group_vol_details}

        create_response = self.rest.srdf_create_device_pair(
            array_id, rdf_group_no, mode, device_id, rep_extra_specs, True)
        mck_create.assert_called_once_with(
            array_id, 'replication', ref_resource, ref_payload)
        mck_get.assert_called_once_with(
            array_id, rdf_group_no, device_id)
        self.assertEqual(ref_response, create_response)

    @mock.patch.object(
        rest.PowerMaxRest, 'get_rdf_pair_volume',
        return_value=tpd.PowerMaxData.rdf_group_vol_details)
    @mock.patch.object(rest.PowerMaxRest, 'wait_for_job')
    @mock.patch.object(rest.PowerMaxRest, 'create_resource',
                       return_value=(200, 'job'))
    def test_srdf_create_device_pair_sync(
            self, mck_create, mck_wait, mck_get):
        array_id = self.data.array
        remote_array = self.data.remote_array
        rdf_group_no = self.data.rdf_group_no_1
        mode = utils.REP_SYNC
        device_id = self.data.device_id
        tgt_device_id = self.data.device_id2
        rep_extra_specs = self.data.rep_extra_specs
        rep_extra_specs[utils.ARRAY] = remote_array

        ref_payload = {
            'executionOption': 'ASYNCHRONOUS', 'rdfMode': mode,
            'localDeviceListCriteriaParam': {'localDeviceList': [device_id]},
            'rdfType': 'RDF1', 'establish': 'true'}
        ref_resource = 'rdf_group/%(rdfg)s/volume' % {'rdfg': rdf_group_no}
        ref_response = {
            'array': array_id, 'remote_array': remote_array,
            'src_device': device_id, 'tgt_device': tgt_device_id,
            'session_info': self.data.rdf_group_vol_details}

        create_response = self.rest.srdf_create_device_pair(
            array_id, rdf_group_no, mode, device_id, rep_extra_specs, True)
        mck_create.assert_called_once_with(
            array_id, 'replication', ref_resource, ref_payload)
        mck_get.assert_called_once_with(
            array_id, rdf_group_no, device_id)
        self.assertEqual(ref_response, create_response)

    @mock.patch.object(rest.PowerMaxRest, 'get_storage_group_rdf_group_state',
                       return_value=[utils.RDF_CONSISTENT_STATE])
    def test_wait_for_rdf_group_sync(self, mck_get):
        array_id = self.data.array
        rdf_group_no = self.data.rdf_group_no_1
        sg_name = self.data.default_sg_re_enabled
        rep_extra_specs = deepcopy(self.data.rep_extra_specs)
        rep_extra_specs['sync_retries'] = 2
        rep_extra_specs['sync_interval'] = 1

        self.rest.wait_for_rdf_group_sync(
            array_id, sg_name, rdf_group_no, rep_extra_specs)
        mck_get.assert_called_once_with(array_id, sg_name, rdf_group_no)

    @mock.patch.object(rest.PowerMaxRest, 'get_storage_group_rdf_group_state',
                       return_value=[utils.RDF_SYNCINPROG_STATE])
    def test_wait_for_rdf_group_sync_fail(self, mck_get):
        array_id = self.data.array
        rdf_group_no = self.data.rdf_group_no_1
        sg_name = self.data.default_sg_re_enabled
        rep_extra_specs = deepcopy(self.data.rep_extra_specs)
        rep_extra_specs['sync_retries'] = 1
        rep_extra_specs['sync_interval'] = 1

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.rest.wait_for_rdf_group_sync,
                          array_id, sg_name, rdf_group_no, rep_extra_specs)

    @mock.patch.object(rest.PowerMaxRest, 'get_rdf_pair_volume',
                       return_value=tpd.PowerMaxData.rdf_group_vol_details)
    def test_wait_for_rdf_pair_sync(self, mck_get):
        array_id = self.data.array
        rdf_group_no = self.data.rdf_group_no_1
        sg_name = self.data.default_sg_re_enabled
        rep_extra_specs = deepcopy(self.data.rep_extra_specs)
        rep_extra_specs['sync_retries'] = 2
        rep_extra_specs['sync_interval'] = 1

        self.rest.wait_for_rdf_pair_sync(
            array_id, sg_name, rdf_group_no, rep_extra_specs)
        mck_get.assert_called_once_with(array_id, sg_name, rdf_group_no)

    @mock.patch.object(
        rest.PowerMaxRest, 'get_rdf_pair_volume',
        return_value=tpd.PowerMaxData.rdf_group_vol_details_not_synced)
    def test_wait_for_rdf_pair_sync_fail(self, mck_get):
        array_id = self.data.array
        rdf_group_no = self.data.rdf_group_no_1
        sg_name = self.data.default_sg_re_enabled
        rep_extra_specs = deepcopy(self.data.rep_extra_specs)
        rep_extra_specs['sync_retries'] = 1
        rep_extra_specs['sync_interval'] = 1

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.rest.wait_for_rdf_pair_sync,
                          array_id, sg_name, rdf_group_no, rep_extra_specs)

    def test_validate_unisphere_version_unofficial_success(self):
        version = 'T9.2.0.1054'
        returned_version = {'version': version}
        with mock.patch.object(self.rest, "request",
                               return_value=(200,
                                             returned_version)) as mock_req:
            valid_version = self.rest.validate_unisphere_version()
            self.assertTrue(valid_version)
        request_count = mock_req.call_count
        self.assertEqual(1, request_count)

    def test_validate_unisphere_version_unofficial_failure(self):
        version = 'T9.0.0.1054'
        returned_version = {'version': version}
        with mock.patch.object(self.rest, "request",
                               return_value=(200,
                                             returned_version)):
            valid_version = self.rest.validate_unisphere_version()
            self.assertFalse(valid_version)

    def test_validate_unisphere_version_unofficial_greater_than(self):
        version = 'T9.2.0.1054'
        returned_version = {'version': version}
        with mock.patch.object(self.rest, "request",
                               return_value=(200,
                                             returned_version)) as mock_req:
            valid_version = self.rest.validate_unisphere_version()
            self.assertTrue(valid_version)
        request_count = mock_req.call_count
        self.assertEqual(1, request_count)

    @mock.patch.object(rest.PowerMaxRest, '_build_uri_kwargs')
    @mock.patch.object(rest.PowerMaxRest, '_build_uri_legacy_args')
    def test_build_uri_legacy(self, mck_build_legacy, mck_build_kwargs):
        self.rest.build_uri('array', f_key='test')
        mck_build_legacy.assert_called_once()
        mck_build_kwargs.assert_not_called()

    @mock.patch.object(rest.PowerMaxRest, '_build_uri_kwargs')
    @mock.patch.object(rest.PowerMaxRest, '_build_uri_legacy_args')
    def test_build_uri_kwargs(self, mck_build_legacy, mck_build_kwargs):
        self.rest.build_uri(array='test', f_key='test')
        mck_build_legacy.assert_not_called()
        mck_build_kwargs.assert_called_once()

    def test_build_uri_legacy_args_private_no_version(self):
        target_uri = self.rest._build_uri_legacy_args(
            self.data.array, 'sloprovisioning', 'storagegroup',
            resource_name='test-sg', private=True, no_version=True)
        expected_uri = (
            '/private/sloprovisioning/symmetrix/%(arr)s/storagegroup/test-sg' %
            {'arr': self.data.array})
        self.assertEqual(target_uri, expected_uri)

    def test_build_uri_legacy_args_public_version(self):
        target_uri = self.rest._build_uri_legacy_args(
            self.data.array, 'sloprovisioning', 'storagegroup',
            resource_name='test-sg')
        expected_uri = (
            '/%(ver)s/sloprovisioning/symmetrix/%(arr)s/storagegroup/test-sg' %
            {'ver': rest.U4V_VERSION, 'arr': self.data.array})
        self.assertEqual(target_uri, expected_uri)

    def test_build_uri_kwargs_private_no_version(self):
        target_uri = self.rest._build_uri_kwargs(
            no_version=True, private=True, category='test')
        expected_uri = '/private/test'
        self.assertEqual(target_uri, expected_uri)

    def test_build_uri_kwargs_public_version(self):
        target_uri = self.rest._build_uri_kwargs(category='test')
        expected_uri = '/%(ver)s/test' % {'ver': rest.U4V_VERSION}
        self.assertEqual(target_uri, expected_uri)

    def test_build_uri_kwargs_full_uri(self):
        target_uri = self.rest._build_uri_kwargs(
            category='test-cat',
            resource_level='res-level', resource_level_id='id1',
            resource_type='res-type', resource_type_id='id2',
            resource='res', resource_id='id3',
            object_type='obj', object_type_id='id4')
        expected_uri = (
            '/%(ver)s/test-cat/res-level/id1/res-type/id2/res/id3/obj/id4' % {
                'ver': rest.U4V_VERSION})
        self.assertEqual(target_uri, expected_uri)

    @mock.patch.object(
        rest.PowerMaxRest, 'request', return_value=(200, {'success': True}))
    def test_post_request(self, mck_request):
        test_uri = '/92/test/uri'
        test_op = 'performance metrics'
        test_filters = {'filters': False}
        response_obj = self.rest.post_request(test_uri, test_op, test_filters)
        mck_request.assert_called_once_with(
            test_uri, rest.POST, request_object=test_filters)
        self.assertEqual(response_obj, {'success': True})

    def test_get_ip_interface_physical_port(self):
        array_id = self.data.array
        virtual_port = self.data.iscsi_dir_virtual_port
        ip_address = self.data.ip
        response_dir_port = self.rest.get_ip_interface_physical_port(
            array_id, virtual_port, ip_address)
        self.assertEqual(self.data.iscsi_dir_port, response_dir_port)

    @mock.patch.object(
        rest.PowerMaxRest, 'get_request',
        side_effect=[tpd.PowerMaxData.director_port_keys_empty,
                     tpd.PowerMaxData.director_port_keys_multiple])
    def test_get_ip_interface_physical_port_exceptions(self, mck_get):
        array_id = self.data.array
        virtual_port = self.data.iscsi_dir_virtual_port
        ip_address = self.data.ip

        # No physical port keys returned
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.rest.get_ip_interface_physical_port,
            array_id, virtual_port, ip_address)
        # Multiple physical port keys returned
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.rest.get_ip_interface_physical_port,
            array_id, virtual_port, ip_address)
