# Copyright (c) 2016 EMC Corporation.
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

from unittest import mock

from cinder import exception
from cinder.tests.unit.volume.drivers.dell_emc.vnx import fake_storops \
    as storops
from cinder.tests.unit.volume.drivers.dell_emc.vnx import res_mock
from cinder.tests.unit.volume.drivers.dell_emc.vnx import test_base
from cinder.volume.drivers.dell_emc.vnx import client
from cinder.volume.drivers.dell_emc.vnx import common


class TestExtraSpecs(test_base.TestCase):
    def test_valid_extra_spec(self):
        extra_spec = {
            'provisioning:type': 'deduplicated',
            'storagetype:tiering': 'nomovement',
        }
        spec_obj = common.ExtraSpecs(extra_spec)
        self.assertEqual(storops.VNXProvisionEnum.DEDUPED,
                         spec_obj.provision)
        self.assertEqual(storops.VNXTieringEnum.NO_MOVE,
                         spec_obj.tier)

    def test_extra_spec_case_insensitive(self):
        extra_spec = {
            'provisioning:type': 'Thin',
            'storagetype:tiering': 'StartHighThenAuto',
        }
        spec_obj = common.ExtraSpecs(extra_spec)
        self.assertEqual(storops.VNXProvisionEnum.THIN,
                         spec_obj.provision)
        self.assertEqual(storops.VNXTieringEnum.HIGH_AUTO,
                         spec_obj.tier)

    def test_empty_extra_spec(self):
        extra_spec = {}
        common.ExtraSpecs.set_defaults(storops.VNXProvisionEnum.THICK,
                                       storops.VNXTieringEnum.HIGH_AUTO)
        spec_obj = common.ExtraSpecs(extra_spec)
        self.assertEqual(storops.VNXProvisionEnum.THICK, spec_obj.provision)
        self.assertEqual(storops.VNXTieringEnum.HIGH_AUTO, spec_obj.tier)

    def test_invalid_provision(self):
        extra_spec = {
            'provisioning:type': 'invalid',
        }
        self.assertRaises(exception.InvalidVolumeType,
                          common.ExtraSpecs,
                          extra_spec)

    def test_invalid_tiering(self):
        extra_spec = {
            'storagetype:tiering': 'invalid',
        }
        self.assertRaises(exception.InvalidVolumeType,
                          common.ExtraSpecs,
                          extra_spec)

    def test_validate_extra_spec_dedup_and_tier_failed(self):
        spec_obj = common.ExtraSpecs({
            'storagetype:pool': 'fake_pool',
            'provisioning:type': 'deduplicated',
            'storagetype:tiering': 'auto',
        })
        enabler_status = common.VNXEnablerStatus(
            dedup=True, fast=True, thin=True)
        self.assertRaises(exception.InvalidVolumeType,
                          spec_obj.validate,
                          enabler_status)

    def test_tier_is_not_set_to_default_for_dedup_provision(self):
        common.ExtraSpecs.set_defaults(storops.VNXProvisionEnum.THICK,
                                       storops.VNXTieringEnum.HIGH_AUTO)
        spec_obj = common.ExtraSpecs({'provisioning:type': 'deduplicated'})
        self.assertEqual(storops.VNXProvisionEnum.DEDUPED, spec_obj.provision)
        self.assertIsNone(spec_obj.tier)

    def test_validate_extra_spec_is_valid(self):
        spec_obj = common.ExtraSpecs({
            'storagetype:pool': 'fake_pool',
            'provisioning:type': 'thin',
            'storagetype:tiering': 'auto',
        })
        enabler_status = common.VNXEnablerStatus(
            dedup=True, fast=True, thin=True)
        re = spec_obj.validate(enabler_status)
        self.assertTrue(re)

    def test_validate_extra_spec_dedup_invalid(self):
        spec_obj = common.ExtraSpecs({
            'provisioning:type': 'deduplicated',
        })
        enabler_status = common.VNXEnablerStatus(dedup=False)
        self.assertRaises(exception.InvalidVolumeType,
                          spec_obj.validate,
                          enabler_status)

    def test_validate_extra_spec_compress_invalid(self):
        spec_obj = common.ExtraSpecs({
            'provisioning:type': 'compressed',
        })
        enabler_status = common.VNXEnablerStatus(compression=False)
        self.assertRaises(exception.InvalidVolumeType,
                          spec_obj.validate,
                          enabler_status)

    def test_validate_extra_spec_no_thin_invalid(self):
        spec_obj = common.ExtraSpecs({
            'provisioning:type': 'compressed',
        })
        enabler_status = common.VNXEnablerStatus(compression=True, thin=False)
        self.assertRaises(exception.InvalidVolumeType,
                          spec_obj.validate,
                          enabler_status)

    def test_validate_extra_spec_tier_invalid(self):
        spec_obj = common.ExtraSpecs({
            'storagetype:tiering': 'auto',
        })
        enabler_status = common.VNXEnablerStatus(
            dedup=True, fast=False, compression=True, snap=True, thin=True)
        self.assertRaises(exception.InvalidVolumeType,
                          spec_obj.validate,
                          enabler_status)

    def test_get_raw_data(self):
        spec_obj = common.ExtraSpecs({'key1': 'value1'})
        self.assertIn('key1', spec_obj)
        self.assertNotIn('key2', spec_obj)
        self.assertEqual('value1', spec_obj['key1'])

    @res_mock.mock_storage_resources
    def test_generate_extra_specs_from_lun(self, mocked_res):
        lun = mocked_res['lun']
        spec = common.ExtraSpecs.from_lun(lun)
        self.assertEqual(storops.VNXProvisionEnum.COMPRESSED, spec.provision)
        self.assertEqual(storops.VNXTieringEnum.HIGH, spec.tier)

        lun = mocked_res['deduped_lun']
        spec = common.ExtraSpecs.from_lun(lun)
        self.assertEqual(storops.VNXProvisionEnum.DEDUPED, spec.provision)
        self.assertIsNone(spec.tier)

    @res_mock.mock_storage_resources
    def test_extra_specs_match_with_lun(self, mocked_res):
        lun = mocked_res['lun']
        spec_obj = common.ExtraSpecs({
            'provisioning:type': 'thin',
            'storagetype:tiering': 'nomovement',
        })
        self.assertTrue(spec_obj.match_with_lun(lun))

        lun = mocked_res['deduped_lun']
        spec_obj = common.ExtraSpecs({
            'provisioning:type': 'deduplicated',
        })
        self.assertTrue(spec_obj.match_with_lun(lun))

    @res_mock.mock_storage_resources
    def test_extra_specs_not_match_with_lun(self, mocked_res):
        lun = mocked_res['lun']
        spec_obj = common.ExtraSpecs({
            'provisioning:type': 'thick',
            'storagetype:tiering': 'nomovement',
        })
        self.assertFalse(spec_obj.match_with_lun(lun))


class FakeConfiguration(object):
    def __init__(self):
        self.replication_device = []


class TestReplicationDeviceList(test_base.TestCase):
    def setUp(self):
        super(TestReplicationDeviceList, self).setUp()
        self.configuration = FakeConfiguration()
        replication_devices = []
        device = {'backend_id': 'array_id_1',
                  'san_ip': '192.168.1.1',
                  'san_login': 'admin',
                  'san_password': 'admin',
                  'storage_vnx_authentication_type': 'global',
                  'storage_vnx_security_file_dir': '/home/stack/'}
        replication_devices.append(device)
        self.configuration.replication_device = replication_devices

    def test_get_device(self):
        devices_list = common.ReplicationDeviceList(self.configuration)
        device = devices_list.get_device('array_id_1')
        self.assertIsNotNone(device)
        self.assertEqual('192.168.1.1', device.san_ip)
        self.assertEqual('admin', device.san_login)
        self.assertEqual('admin', device.san_password)
        self.assertEqual('global', device.storage_vnx_authentication_type)
        self.assertEqual('/home/stack/', device.storage_vnx_security_file_dir)

    def test_device_no_backend_id(self):
        device = {'san_ip': '192.168.1.2'}
        config = FakeConfiguration()
        config.replication_device = [device]
        self.assertRaises(
            exception.InvalidInput,
            common.ReplicationDeviceList, config)

    def test_device_no_secfile(self):
        device = {'backend_id': 'test_id',
                  'san_ip': '192.168.1.2'}
        config = FakeConfiguration()
        config.replication_device = [device]
        rep_list = common.ReplicationDeviceList(config)
        self.assertIsNone(rep_list[0].storage_vnx_security_file_dir)

    def test_get_device_not_found(self):
        devices_list = common.ReplicationDeviceList(self.configuration)
        device = devices_list.get_device('array_id_not_existed')
        self.assertIsNone(device)

    def test_devices(self):
        devices_list = common.ReplicationDeviceList(self.configuration)
        self.assertEqual(1, len(devices_list.devices))
        self.assertEqual(1, len(devices_list))
        self.assertIsNotNone(devices_list[0])

    def test_get_backend_ids(self):
        backend_ids = common.ReplicationDeviceList.get_backend_ids(
            self.configuration)
        self.assertEqual(1, len(backend_ids))
        self.assertIn('array_id_1', backend_ids)


class TestVNXMirrorView(test_base.TestCase):
    def setUp(self):
        super(TestVNXMirrorView, self).setUp()
        self.primary_client = mock.create_autospec(client.Client)
        self.secondary_client = mock.create_autospec(client.Client)
        self.mirror_view = common.VNXMirrorView(
            self.primary_client, self.secondary_client)

    def test_create_mirror(self):
        self.mirror_view.create_mirror('mirror_test', 11)
        self.primary_client.create_mirror.assert_called_once_with(
            'mirror_test', 11)

    def test_create_secondary_lun(self):
        self.mirror_view.create_secondary_lun('pool_name', 'lun_name',
                                              10, 'thick', 'auto')
        self.secondary_client.create_lun.assert_called_once_with(
            'pool_name', 'lun_name', 10, 'thick', 'auto')

    def test_delete_secondary_lun(self):
        self.mirror_view.delete_secondary_lun('lun_name')
        self.secondary_client.delete_lun.assert_called_once_with('lun_name')

    def test_delete_mirror(self):
        self.mirror_view.delete_mirror('mirror_name')
        self.primary_client.delete_mirror.assert_called_once_with(
            'mirror_name')

    def test_add_image(self):
        self.secondary_client.get_available_ip.return_value = '192.168.1.2'
        self.mirror_view.add_image('mirror_name', 111)
        self.secondary_client.get_available_ip.assert_called_once_with()
        self.primary_client.add_image.assert_called_once_with(
            'mirror_name', '192.168.1.2', 111)

    def test_remove_image(self):
        self.mirror_view.remove_image('mirror_remove')
        self.primary_client.remove_image.assert_called_once_with(
            'mirror_remove')

    def test_fracture_image(self):
        self.mirror_view.fracture_image('mirror_fracture')
        self.primary_client.fracture_image.assert_called_once_with(
            'mirror_fracture')

    def test_promote_image(self):
        self.mirror_view.promote_image('mirror_promote')
        self.secondary_client.promote_image.assert_called_once_with(
            'mirror_promote')

    def test_destroy_mirror(self):
        mv = mock.Mock()
        mv.existed = True
        self.primary_client.get_mirror.return_value = mv
        self.mirror_view.destroy_mirror('mirror_name', 'sec_lun_name')
        self.primary_client.get_mirror.assert_called_once_with(
            'mirror_name')
        self.primary_client.fracture_image.assert_called_once_with(
            'mirror_name')
        self.primary_client.remove_image.assert_called_once_with(
            'mirror_name')
        self.primary_client.delete_mirror.assert_called_once_with(
            'mirror_name')
        self.secondary_client.delete_lun.assert_called_once_with(
            'sec_lun_name')

    def test_destroy_mirror_not_existed(self):
        mv = mock.Mock()
        mv.existed = False
        self.primary_client.get_mirror.return_value = mv
        self.mirror_view.destroy_mirror('mirror_name', 'sec_lun_name')
        self.primary_client.get_mirror.assert_called_once_with(
            'mirror_name')
        self.assertFalse(self.primary_client.fracture_image.called)

    def test_create_mirror_group(self):
        self.mirror_view.create_mirror_group('test_group')
        self.primary_client.create_mirror_group.assert_called_once_with(
            'test_group')

    def test_delete_mirror_group(self):
        self.mirror_view.delete_mirror_group('test_group')
        self.primary_client.delete_mirror_group.assert_called_once_with(
            'test_group')

    def test_add_mirror(self):
        self.mirror_view.add_mirror('test_group', 'test_mirror')
        self.primary_client.add_mirror.assert_called_once_with(
            'test_group', 'test_mirror')

    def test_remove_mirror(self):
        self.mirror_view.remove_mirror('test_group', 'test_mirror')
        self.primary_client.remove_mirror('test_group', 'test_mirror')

    def test_sync_mirror_group(self):
        self.mirror_view.sync_mirror_group('test_group')
        self.primary_client.sync_mirror_group.assert_called_once_with(
            'test_group')

    def test_promote_mirror_group(self):
        self.mirror_view.promote_mirror_group('test_group')
        self.secondary_client.promote_mirror_group.assert_called_once_with(
            'test_group')

    def test_fracture_mirror_group(self):
        self.mirror_view.fracture_mirror_group('test_group')
        self.primary_client.fracture_mirror_group.assert_called_once_with(
            'test_group')
