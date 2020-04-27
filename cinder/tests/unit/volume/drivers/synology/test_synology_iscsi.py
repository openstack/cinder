# Copyright (c) 2016 Synology Co., Ltd.
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

"""Tests for the Synology iSCSI volume driver."""

from unittest import mock

from cinder import exception
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.synology import synology_common as common
from cinder.volume.drivers.synology import synology_iscsi

VOLUME_ID = fake.VOLUME_ID
TARGET_NAME_PREFIX = 'Cinder-Target-'
IP = '10.10.10.10'
IQN = 'iqn.2000-01.com.synology:' + TARGET_NAME_PREFIX + VOLUME_ID
TRG_ID = 1
VOLUME = {
    'name': fake.VOLUME_NAME,
    'id': VOLUME_ID,
    'display_name': 'fake_volume',
    'size': 10,
    'provider_location': '%s:3260,%d %s 1' % (IP, TRG_ID, IQN),
}
NEW_VOLUME_ID = fake.VOLUME2_ID
IQN2 = 'iqn.2000-01.com.synology:' + TARGET_NAME_PREFIX + NEW_VOLUME_ID
NEW_TRG_ID = 2
NEW_VOLUME = {
    'name': fake.VOLUME2_NAME,
    'id': NEW_VOLUME_ID,
    'display_name': 'new_fake_volume',
    'size': 10,
    'provider_location': '%s:3260,%d %s 1' % (IP, NEW_TRG_ID, IQN2),
}
SNAPSHOT_ID = fake.SNAPSHOT_ID
SNAPSHOT = {
    'name': fake.SNAPSHOT_NAME,
    'id': SNAPSHOT_ID,
    'volume_id': VOLUME_ID,
    'volume_name': VOLUME['name'],
    'volume_size': 10,
    'display_name': 'fake_snapshot',
}
DS_SNAPSHOT_UUID = 'ca86a56a-40d8-4210-974c-ef15dbf01cba'
SNAPSHOT_METADATA = {
    'metadata': {
        'ds_snapshot_UUID': DS_SNAPSHOT_UUID
    }
}
INITIATOR_IQN = 'iqn.1993-08.org.debian:01:604af6a341'
CONNECTOR = {
    'initiator': INITIATOR_IQN,
}
CONTEXT = {
}
LOCAL_PATH = '/dev/isda'
IMAGE_SERVICE = 'image_service'
IMAGE_ID = 1
IMAGE_META = {
    'id': IMAGE_ID
}
NODE_UUID = '72003c93-2db2-4f00-a169-67c5eae86bb1'
HOST = {
}


class SynoISCSIDriverTestCase(test.TestCase):

    @mock.patch.object(common.SynoCommon,
                       '_get_node_uuid',
                       return_value=NODE_UUID)
    @mock.patch.object(common, 'APIRequest')
    def setUp(self, _request, _get_node_uuid):
        super(SynoISCSIDriverTestCase, self).setUp()

        self.conf = self.setup_configuration()
        self.driver = synology_iscsi.SynoISCSIDriver(configuration=self.conf)
        self.driver.common = common.SynoCommon(self.conf, 'iscsi')

    def setup_configuration(self):
        config = mock.Mock(spec=conf.Configuration)
        config.use_chap_auth = False
        config.target_protocol = 'iscsi'
        config.target_ip_address = IP
        config.synology_admin_port = 5000
        config.synology_username = 'admin'
        config.synology_password = 'admin'
        config.synology_ssl_verify = True
        config.synology_one_time_pass = '123456'
        config.volume_dd_blocksize = 1

        return config

    def test_check_for_setup_error(self):
        self.driver.common.check_for_setup_error = mock.Mock()

        result = self.driver.check_for_setup_error()

        self.driver.common.check_for_setup_error.assert_called_with()
        self.assertIsNone(result)

    def test_create_volume(self):
        self.driver.common.create_volume = mock.Mock()

        result = self.driver.create_volume(VOLUME)

        self.driver.common.create_volume.assert_called_with(VOLUME)
        self.assertIsNone(result)

    def test_delete_volume(self):
        self.driver.common.delete_volume = mock.Mock()

        result = self.driver.delete_volume(VOLUME)

        self.driver.common.delete_volume.assert_called_with(VOLUME)
        self.assertIsNone(result)

    def test_create_cloned_volume(self):
        self.driver.common.create_cloned_volume = mock.Mock()

        result = self.driver.create_cloned_volume(VOLUME, NEW_VOLUME)

        self.driver.common.create_cloned_volume.assert_called_with(
            VOLUME, NEW_VOLUME)
        self.assertIsNone(result)

    def test_extend_volume(self):
        new_size = 20

        self.driver.common.extend_volume = mock.Mock()

        result = self.driver.extend_volume(VOLUME, new_size)

        self.driver.common.extend_volume.assert_called_with(
            VOLUME, new_size)
        self.assertIsNone(result)

    def test_extend_volume_wrong_size(self):
        wrong_new_size = 1

        self.driver.common.extend_volume = mock.Mock()

        result = self.driver.extend_volume(VOLUME, wrong_new_size)

        self.driver.common.extend_volume.assert_not_called()
        self.assertIsNone(result)

    def test_create_volume_from_snapshot(self):
        self.driver.common.create_volume_from_snapshot = mock.Mock()

        result = self.driver.create_volume_from_snapshot(VOLUME, SNAPSHOT)

        (self.driver.common.
            create_volume_from_snapshot.assert_called_with(VOLUME, SNAPSHOT))
        self.assertIsNone(result)

    def test_update_migrated_volume(self):
        fake_ret = {'_name_id': VOLUME['id']}
        status = ''
        self.driver.common.update_migrated_volume = (
            mock.Mock(return_value=fake_ret))

        result = self.driver.update_migrated_volume(CONTEXT,
                                                    VOLUME,
                                                    NEW_VOLUME,
                                                    status)

        (self.driver.common.update_migrated_volume.
            assert_called_with(VOLUME, NEW_VOLUME))
        self.assertEqual(fake_ret, result)

    def test_create_snapshot(self):
        self.driver.common.create_snapshot = (
            mock.Mock(return_value=SNAPSHOT_METADATA))

        result = self.driver.create_snapshot(SNAPSHOT)

        self.driver.common.create_snapshot.assert_called_with(SNAPSHOT)
        self.assertDictEqual(SNAPSHOT_METADATA, result)

    def test_delete_snapshot(self):
        self.driver.common.delete_snapshot = mock.Mock()

        result = self.driver.delete_snapshot(SNAPSHOT)

        self.driver.common.delete_snapshot.assert_called_with(SNAPSHOT)
        self.assertIsNone(result)

    def test_get_volume_stats(self):
        self.driver.common.update_volume_stats = mock.MagicMock()

        result = self.driver.get_volume_stats(True)

        self.driver.common.update_volume_stats.assert_called_with()
        self.assertEqual(self.driver.stats, result)

        result = self.driver.get_volume_stats(False)

        self.driver.common.update_volume_stats.assert_called_with()
        self.assertEqual(self.driver.stats, result)

    def test_get_volume_stats_error(self):
        self.driver.common.update_volume_stats = (
            mock.MagicMock(side_effect=exception.VolumeDriverException(
                message='dont care')))

        self.assertRaises(exception.VolumeDriverException,
                          self.driver.get_volume_stats,
                          True)

    def test_create_export(self):
        provider_auth = 'CHAP username password'
        provider_location = '%s:3260,%d %s 1' % (IP, TRG_ID, IQN)

        self.driver.common.is_lun_mapped = mock.Mock(return_value=False)
        self.driver.common.create_iscsi_export = (
            mock.Mock(return_value=(IQN, TRG_ID, provider_auth)))
        self.driver.common.get_provider_location = (
            mock.Mock(return_value=provider_location))

        result = self.driver.create_export(CONTEXT, VOLUME, CONNECTOR)

        self.driver.common.is_lun_mapped.assert_called_with(VOLUME['name'])
        (self.driver.common.create_iscsi_export.
            assert_called_with(VOLUME['name'], VOLUME['id']))
        self.driver.common.get_provider_location.assert_called_with(IQN,
                                                                    TRG_ID)
        self.assertEqual(provider_location, result['provider_location'])
        self.assertEqual(provider_auth, result['provider_auth'])

    def test_create_export_is_mapped(self):
        self.driver.common.is_lun_mapped = mock.Mock(return_value=True)
        self.driver.common.create_iscsi_export = mock.Mock()
        self.driver.common.get_provider_location = mock.Mock()

        result = self.driver.create_export(CONTEXT, VOLUME, CONNECTOR)

        self.driver.common.is_lun_mapped.assert_called_with(VOLUME['name'])
        self.driver.common.create_iscsi_export.assert_not_called()
        self.driver.common.get_provider_location.assert_not_called()
        self.assertEqual({}, result)

    def test_create_export_error(self):
        provider_location = '%s:3260,%d %s 1' % (IP, TRG_ID, IQN)

        self.driver.common.is_lun_mapped = mock.Mock(return_value=False)
        self.driver.common.create_iscsi_export = (
            mock.Mock(side_effect=exception.InvalidInput(reason='dont care')))
        self.driver.common.get_provider_location = (
            mock.Mock(return_value=provider_location))

        self.assertRaises(exception.ExportFailure,
                          self.driver.create_export,
                          CONTEXT,
                          VOLUME,
                          CONNECTOR)
        self.driver.common.is_lun_mapped.assert_called_with(VOLUME['name'])
        self.driver.common.get_provider_location.assert_not_called()

    def test_remove_export(self):
        self.driver.common.is_lun_mapped = mock.Mock(return_value=True)
        self.driver.common.remove_iscsi_export = mock.Mock()
        self.driver.common.get_iqn_and_trgid = (
            mock.Mock(return_value=('', TRG_ID)))

        _, trg_id = (self.driver.common.
                     get_iqn_and_trgid(VOLUME['provider_location']))
        result = self.driver.remove_export(CONTEXT, VOLUME)

        self.driver.common.is_lun_mapped.assert_called_with(VOLUME['name'])
        (self.driver.common.get_iqn_and_trgid.
            assert_called_with(VOLUME['provider_location']))
        (self.driver.common.remove_iscsi_export.
            assert_called_with(VOLUME['name'], trg_id))
        self.assertIsNone(result)

    def test_remove_export_not_mapped(self):
        self.driver.common.is_lun_mapped = mock.Mock(return_value=False)
        self.driver.common.remove_iscsi_export = mock.Mock()
        self.driver.common.get_iqn_and_trgid = mock.Mock()

        result = self.driver.remove_export(CONTEXT, VOLUME)

        self.driver.common.is_lun_mapped.assert_called_with(VOLUME['name'])
        self.driver.common.get_iqn_and_trgid.assert_not_called()
        self.driver.common.remove_iscsi_export.assert_not_called()
        self.assertIsNone(result)

    def test_remove_export_error(self):
        self.driver.common.is_lun_mapped = mock.Mock(return_value=True)
        self.driver.common.remove_iscsi_export = (
            mock.Mock(side_effect= exception.RemoveExportException(
                volume=VOLUME, reason='dont care')))

        self.assertRaises(exception.RemoveExportException,
                          self.driver.remove_export,
                          CONTEXT,
                          VOLUME)

    def test_remove_export_error_get_lun_mapped(self):
        self.driver.common.remove_iscsi_export = mock.Mock()
        self.driver.common.get_iqn_and_trgid = mock.Mock()
        self.driver.common.is_lun_mapped = (
            mock.Mock(side_effect=common.SynoLUNNotExist(
                message='dont care')))

        result = self.driver.remove_export(CONTEXT, VOLUME)

        self.assertIsNone(result)
        self.driver.common.get_iqn_and_trgid.assert_not_called()
        self.driver.common.remove_iscsi_export.assert_not_called()

    def test_initialize_connection(self):
        iscsi_properties = {
            'target_discovered': False,
            'target_iqn': IQN,
            'target_portal': '%s:3260' % self.conf.target_ip_address,
            'volume_id': VOLUME['id'],
            'access_mode': 'rw',
            'discard': False
        }

        self.driver.common.get_iscsi_properties = (
            mock.Mock(return_value=iscsi_properties))
        self.conf.safe_get = mock.Mock(return_value='iscsi')

        result = self.driver.initialize_connection(VOLUME, CONNECTOR)

        self.driver.common.get_iscsi_properties.assert_called_with(VOLUME)
        self.conf.safe_get.assert_called_with('target_protocol')
        self.assertEqual('iscsi', result['driver_volume_type'])
        self.assertDictEqual(iscsi_properties, result['data'])

    def test_initialize_connection_error(self):
        self.driver.common.get_iscsi_properties = (
            mock.Mock(side_effect=exception.InvalidInput(reason='dont care')))

        self.assertRaises(exception.InvalidInput,
                          self.driver.initialize_connection,
                          VOLUME,
                          CONNECTOR)
