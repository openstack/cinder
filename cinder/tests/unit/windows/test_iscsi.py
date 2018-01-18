# Copyright 2012 Pedro Navarro Perez
# Copyright 2015 Cloudbase Solutions SRL
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

"""
Unit tests for Windows Server 2012 OpenStack Cinder volume driver
"""

import os

import ddt
import mock
from oslo_utils import fileutils
from oslo_utils import units

from cinder import context
from cinder import exception
from cinder.image import image_utils
from cinder import test
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit.windows import db_fakes
from cinder.volume import configuration as conf
from cinder.volume.drivers.windows import iscsi as windows_iscsi


@ddt.ddt
class TestWindowsISCSIDriver(test.TestCase):
    @mock.patch.object(windows_iscsi, 'utilsfactory')
    def setUp(self, mock_utilsfactory):
        super(TestWindowsISCSIDriver, self).setUp()
        self.configuration = conf.Configuration(None)
        self.configuration.append_config_values(windows_iscsi.windows_opts)
        self.flags(windows_iscsi_lun_path='fake_iscsi_lun_path')
        self.flags(image_conversion_dir='fake_image_conversion_dir')

        self._driver = windows_iscsi.WindowsISCSIDriver(
            configuration=self.configuration)

    @mock.patch.object(fileutils, 'ensure_tree')
    def test_do_setup(self, mock_ensure_tree):
        self._driver.do_setup(mock.sentinel.context)

        mock_ensure_tree.assert_has_calls(
            [mock.call('fake_iscsi_lun_path'),
             mock.call('fake_image_conversion_dir')])

    @mock.patch.object(windows_iscsi.WindowsISCSIDriver, '_get_portals')
    def test_check_for_setup_error(self, mock_get_portals):
        self._driver.check_for_setup_error()

        mock_get_portals.assert_called_once_with()

    @ddt.data(True, False)
    def test_get_portals(self, portals_available=True):
        iscsi_port = mock.sentinel.iscsi_port
        available_ips = ['fake_ip0', 'fake_ip1', 'fake_unrequested_ip']
        requested_ips = available_ips[:-1] + ['fake_inexistent_ips']

        available_portals = ([":".join([ip_addr, str(iscsi_port)])
                              for ip_addr in available_ips]
                             if portals_available else [])

        self._driver.configuration = mock.Mock()
        self._driver.configuration.target_port = iscsi_port
        self._driver.configuration.target_ip_address = requested_ips[0]
        self._driver.configuration.iscsi_secondary_ip_addresses = (
            requested_ips[1:])

        self._driver._tgt_utils.get_portal_locations.return_value = (
            available_portals)

        if portals_available:
            portals = self._driver._get_portals()
            self.assertEqual(set(available_portals[:-1]), set(portals))
        else:
            self.assertRaises(exception.VolumeDriverException,
                              self._driver._get_portals)

        self._driver._tgt_utils.get_portal_locations.assert_called_once_with(
            available_only=True,
            fail_if_none_found=True)

    @ddt.data(True, False)
    @mock.patch.object(windows_iscsi.WindowsISCSIDriver, '_get_portals')
    @mock.patch.object(windows_iscsi.WindowsISCSIDriver, '_get_target_name')
    def test_get_host_information(self, multipath, mock_get_target_name,
                                  mock_get_portals):
        tgt_utils = self._driver._tgt_utils

        fake_auth_meth = 'CHAP'
        fake_chap_username = 'fake_chap_username'
        fake_chap_password = 'fake_chap_password'
        fake_target_iqn = 'fake_target_iqn'
        fake_host_info = {'target_iqn': 'fake_target_iqn',
                          'fake_prop': 'fake_value'}
        fake_provider_auth = "%s %s %s" % (fake_auth_meth,
                                           fake_chap_username,
                                           fake_chap_password)
        fake_portals = [mock.sentinel.portal_location0,
                        mock.sentinel.portal_location1]

        volume = fake_volume.fake_volume_obj(mock.sentinel.context,
                                             provider_auth=fake_provider_auth)

        mock_get_target_name.return_value = mock.sentinel.target_name
        mock_get_portals.return_value = fake_portals
        tgt_utils.get_target_information.return_value = fake_host_info

        expected_host_info = dict(fake_host_info,
                                  auth_method=fake_auth_meth,
                                  auth_username=fake_chap_username,
                                  auth_password=fake_chap_password,
                                  target_discovered=False,
                                  target_portal=fake_portals[0],
                                  target_lun=0,
                                  volume_id=volume.id)
        if multipath:
            expected_host_info['target_portals'] = fake_portals
            expected_host_info['target_iqns'] = [fake_target_iqn] * 2
            expected_host_info['target_luns'] = [0] * 2

        host_info = self._driver._get_host_information(volume, multipath)

        self.assertEqual(expected_host_info, host_info)

        mock_get_target_name.assert_called_once_with(volume)
        mock_get_portals.assert_called_once_with()
        tgt_utils.get_target_information.assert_called_once_with(
            mock.sentinel.target_name)

    @mock.patch.object(windows_iscsi.WindowsISCSIDriver,
                       '_get_host_information')
    def test_initialize_connection(self, mock_get_host_info):
        tgt_utils = self._driver._tgt_utils

        volume = fake_volume.fake_volume_obj(mock.sentinel.fake_context)
        fake_initiator = db_fakes.get_fake_connector_info()
        fake_initiator['multipath'] = mock.sentinel.multipath
        fake_host_info = {'fake_host_prop': 'fake_value'}

        mock_get_host_info.return_value = fake_host_info

        expected_conn_info = {'driver_volume_type': 'iscsi',
                              'data': fake_host_info}
        conn_info = self._driver.initialize_connection(volume,
                                                       fake_initiator)

        self.assertEqual(expected_conn_info, conn_info)
        mock_get_host_info.assert_called_once_with(
            volume, mock.sentinel.multipath)
        mock_associate = tgt_utils.associate_initiator_with_iscsi_target
        mock_associate.assert_called_once_with(
            fake_initiator['initiator'],
            volume.provider_location)

    def test_terminate_connection(self):
        volume = fake_volume.fake_volume_obj(mock.sentinel.fake_context)
        fake_initiator = db_fakes.get_fake_connector_info()

        self._driver.terminate_connection(volume, fake_initiator)

        self._driver._tgt_utils.deassociate_initiator.assert_called_once_with(
            fake_initiator['initiator'], volume.provider_location)

    @mock.patch.object(windows_iscsi.WindowsISCSIDriver, 'local_path')
    def test_create_volume(self, mock_local_path):
        volume = fake_volume.fake_volume_obj(mock.sentinel.fake_context)

        self._driver.create_volume(volume)

        mock_local_path.assert_called_once_with(volume)
        self._driver._tgt_utils.create_wt_disk.assert_called_once_with(
            mock_local_path.return_value,
            volume.name,
            size_mb=volume.size * 1024)

    def test_local_path(self):
        volume = fake_volume.fake_volume_obj(mock.sentinel.fake_context)

        fake_lun_path = 'fake_lun_path'
        self.flags(windows_iscsi_lun_path=fake_lun_path)

        disk_format = 'vhd'
        mock_get_fmt = self._driver._tgt_utils.get_supported_disk_format
        mock_get_fmt.return_value = disk_format

        disk_path = self._driver.local_path(volume)

        expected_fname = "%s.%s" % (volume.name, disk_format)
        expected_disk_path = os.path.join(fake_lun_path,
                                          expected_fname)
        self.assertEqual(expected_disk_path, disk_path)
        mock_get_fmt.assert_called_once_with()

    @mock.patch.object(windows_iscsi.WindowsISCSIDriver, 'local_path')
    @mock.patch.object(fileutils, 'delete_if_exists')
    def test_delete_volume(self, mock_delete_if_exists, mock_local_path):
        volume = fake_volume.fake_volume_obj(mock.sentinel.fake_context)

        self._driver.delete_volume(volume)

        mock_local_path.assert_called_once_with(volume)
        self._driver._tgt_utils.remove_wt_disk.assert_called_once_with(
            volume.name)
        mock_delete_if_exists.assert_called_once_with(
            mock_local_path.return_value)

    def test_create_snapshot(self):
        volume = fake_volume.fake_volume_obj(context.get_admin_context())
        snapshot = fake_snapshot.fake_snapshot_obj(context.get_admin_context(),
                                                   volume_id=volume.id)
        snapshot.volume = volume

        self._driver.create_snapshot(snapshot)

        self._driver._tgt_utils.create_snapshot.assert_called_once_with(
            snapshot.volume_name, snapshot.name)

    @mock.patch.object(windows_iscsi.WindowsISCSIDriver, 'local_path')
    def test_create_volume_from_snapshot(self, mock_local_path):
        volume = fake_volume.fake_volume_obj(context.get_admin_context())
        snapshot = fake_snapshot.fake_snapshot_obj(context.get_admin_context())
        snapshot.volume = volume

        self._driver.create_volume_from_snapshot(volume, snapshot)

        self._driver._tgt_utils.export_snapshot.assert_called_once_with(
            snapshot.name, mock_local_path.return_value)
        self._driver._tgt_utils.import_wt_disk.assert_called_once_with(
            mock_local_path.return_value, volume.name)

    def test_delete_snapshot(self):
        snapshot = fake_snapshot.fake_snapshot_obj(context.get_admin_context())

        self._driver.delete_snapshot(snapshot)

        self._driver._tgt_utils.delete_snapshot.assert_called_once_with(
            snapshot.name)

    def test_get_target_name(self):
        volume = fake_volume.fake_volume_obj(mock.sentinel.fake_context)
        expected_target_name = "%s%s" % (
            self._driver.configuration.target_prefix,
            volume.name)

        target_name = self._driver._get_target_name(volume)
        self.assertEqual(expected_target_name, target_name)

    @mock.patch.object(windows_iscsi.WindowsISCSIDriver, '_get_target_name')
    @mock.patch.object(windows_iscsi.utils, 'generate_username')
    @mock.patch.object(windows_iscsi.utils, 'generate_password')
    def test_create_export(self, mock_generate_password,
                           mock_generate_username,
                           mock_get_target_name):
        tgt_utils = self._driver._tgt_utils
        volume = fake_volume.fake_volume_obj(mock.sentinel.fake_context)
        self._driver.configuration.chap_username = None
        self._driver.configuration.chap_password = None
        self._driver.configuration.use_chap_auth = True
        fake_chap_username = 'fake_chap_username'
        fake_chap_password = 'fake_chap_password'

        mock_get_target_name.return_value = mock.sentinel.target_name
        mock_generate_username.return_value = fake_chap_username
        mock_generate_password.return_value = fake_chap_password
        tgt_utils.iscsi_target_exists.return_value = False

        vol_updates = self._driver.create_export(mock.sentinel.context,
                                                 volume,
                                                 mock.sentinel.connector)

        mock_get_target_name.assert_called_once_with(volume)
        tgt_utils.iscsi_target_exists.assert_called_once_with(
            mock.sentinel.target_name)
        tgt_utils.set_chap_credentials.assert_called_once_with(
            mock.sentinel.target_name,
            fake_chap_username,
            fake_chap_password)
        tgt_utils.add_disk_to_target.assert_called_once_with(
            volume.name, mock.sentinel.target_name)

        expected_provider_auth = ' '.join(('CHAP',
                                           fake_chap_username,
                                           fake_chap_password))
        expected_vol_updates = dict(
            provider_location=mock.sentinel.target_name,
            provider_auth=expected_provider_auth)
        self.assertEqual(expected_vol_updates, vol_updates)

    @mock.patch.object(windows_iscsi.WindowsISCSIDriver, '_get_target_name')
    def test_remove_export(self, mock_get_target_name):
        volume = fake_volume.fake_volume_obj(mock.sentinel.fake_context)

        self._driver.remove_export(mock.sentinel.context, volume)

        mock_get_target_name.assert_called_once_with(volume)
        self._driver._tgt_utils.delete_iscsi_target.assert_called_once_with(
            mock_get_target_name.return_value)

    @mock.patch.object(windows_iscsi.WindowsISCSIDriver, 'local_path')
    @mock.patch.object(image_utils, 'temporary_file')
    @mock.patch.object(image_utils, 'fetch_to_vhd')
    @mock.patch('os.unlink')
    def test_copy_image_to_volume(self, mock_unlink, mock_fetch_to_vhd,
                                  mock_tmp_file, mock_local_path):
        tgt_utils = self._driver._tgt_utils
        volume = fake_volume.fake_volume_obj(mock.sentinel.fake_context)

        mock_tmp_file.return_value.__enter__.return_value = (
            mock.sentinel.tmp_vhd_path)
        mock_local_path.return_value = mock.sentinel.vol_vhd_path

        self._driver.copy_image_to_volume(mock.sentinel.context,
                                          volume,
                                          mock.sentinel.image_service,
                                          mock.sentinel.image_id)

        mock_local_path.assert_called_once_with(volume)
        mock_tmp_file.assert_called_once_with(suffix='.vhd')
        image_utils.fetch_to_vhd.assert_called_once_with(
            mock.sentinel.context, mock.sentinel.image_service,
            mock.sentinel.image_id, mock.sentinel.tmp_vhd_path,
            self._driver.configuration.volume_dd_blocksize)

        mock_unlink.assert_called_once_with(mock.sentinel.vol_vhd_path)
        self._driver._vhdutils.convert_vhd.assert_called_once_with(
            mock.sentinel.tmp_vhd_path,
            mock.sentinel.vol_vhd_path,
            tgt_utils.get_supported_vhd_type.return_value)
        self._driver._vhdutils.resize_vhd.assert_called_once_with(
            mock.sentinel.vol_vhd_path,
            volume.size * units.Gi,
            is_file_max_size=False)

        tgt_utils.change_wt_disk_status.assert_has_calls(
            [mock.call(volume.name, enabled=False),
             mock.call(volume.name, enabled=True)])

    @mock.patch.object(windows_iscsi.uuidutils, 'generate_uuid')
    def test_temporary_snapshot(self, mock_generate_uuid):
        tgt_utils = self._driver._tgt_utils
        mock_generate_uuid.return_value = mock.sentinel.snap_uuid
        expected_snap_name = '%s-tmp-snapshot-%s' % (
            mock.sentinel.volume_name, mock.sentinel.snap_uuid)

        with self._driver._temporary_snapshot(
                mock.sentinel.volume_name) as snap_name:
            self.assertEqual(expected_snap_name, snap_name)
            tgt_utils.create_snapshot.assert_called_once_with(
                mock.sentinel.volume_name, expected_snap_name)

        tgt_utils.delete_snapshot.assert_called_once_with(
            expected_snap_name)

    @mock.patch.object(windows_iscsi.WindowsISCSIDriver, '_temporary_snapshot')
    @mock.patch.object(image_utils, 'upload_volume')
    @mock.patch.object(fileutils, 'delete_if_exists')
    def test_copy_volume_to_image(self, mock_delete_if_exists,
                                  mock_upload_volume,
                                  mock_tmp_snap):
        tgt_utils = self._driver._tgt_utils

        disk_format = 'vhd'
        fake_image_meta = db_fakes.get_fake_image_meta()
        volume = fake_volume.fake_volume_obj(mock.sentinel.fake_context)
        fake_img_conv_dir = 'fake_img_conv_dir'
        self.flags(image_conversion_dir=fake_img_conv_dir)

        tgt_utils.get_supported_disk_format.return_value = disk_format
        mock_tmp_snap.return_value.__enter__.return_value = (
            mock.sentinel.tmp_snap_name)

        expected_tmp_vhd_path = os.path.join(
            fake_img_conv_dir,
            fake_image_meta['id'] + '.' + disk_format)

        self._driver.copy_volume_to_image(
            mock.sentinel.context, volume,
            mock.sentinel.image_service,
            fake_image_meta)

        mock_tmp_snap.assert_called_once_with(volume.name)
        tgt_utils.export_snapshot.assert_called_once_with(
            mock.sentinel.tmp_snap_name,
            expected_tmp_vhd_path)
        mock_upload_volume.assert_called_once_with(
            mock.sentinel.context, mock.sentinel.image_service,
            fake_image_meta, expected_tmp_vhd_path, 'vhd')
        mock_delete_if_exists.assert_called_once_with(
            expected_tmp_vhd_path)

    @mock.patch.object(windows_iscsi.WindowsISCSIDriver, '_temporary_snapshot')
    @mock.patch.object(windows_iscsi.WindowsISCSIDriver, 'local_path')
    def test_create_cloned_volume(self, mock_local_path,
                                  mock_tmp_snap):
        tgt_utils = self._driver._tgt_utils

        volume = fake_volume.fake_volume_obj(mock.sentinel.fake_context)
        src_volume = fake_volume.fake_volume_obj(mock.sentinel.fake_context)

        mock_tmp_snap.return_value.__enter__.return_value = (
            mock.sentinel.tmp_snap_name)
        mock_local_path.return_value = mock.sentinel.vol_vhd_path

        self._driver.create_cloned_volume(volume, src_volume)

        mock_tmp_snap.assert_called_once_with(src_volume.name)
        tgt_utils.export_snapshot.assert_called_once_with(
            mock.sentinel.tmp_snap_name,
            mock.sentinel.vol_vhd_path)
        self._driver._vhdutils.resize_vhd.assert_called_once_with(
            mock.sentinel.vol_vhd_path, volume.size * units.Gi,
            is_file_max_size=False)
        tgt_utils.import_wt_disk.assert_called_once_with(
            mock.sentinel.vol_vhd_path, volume.name)

    @mock.patch('os.path.splitdrive')
    def test_get_capacity_info(self, mock_splitdrive):
        mock_splitdrive.return_value = (mock.sentinel.drive,
                                        mock.sentinel.path_tail)
        fake_size_gb = 2
        fake_free_space_gb = 1
        self._driver._hostutils.get_volume_info.return_value = (
            fake_size_gb * units.Gi,
            fake_free_space_gb * units.Gi)

        total_gb, free_gb = self._driver._get_capacity_info()

        self.assertEqual(fake_size_gb, total_gb)
        self.assertEqual(fake_free_space_gb, free_gb)

        self._driver._hostutils.get_volume_info.assert_called_once_with(
            mock.sentinel.drive)
        mock_splitdrive.assert_called_once_with('fake_iscsi_lun_path')

    @mock.patch.object(windows_iscsi.WindowsISCSIDriver, '_get_capacity_info')
    def test_update_volume_stats(self, mock_get_capacity_info):
        mock_get_capacity_info.return_value = (
            mock.sentinel.size_gb,
            mock.sentinel.free_space_gb)

        self.flags(volume_backend_name='volume_backend_name')
        self.flags(reserved_percentage=10)

        expected_volume_stats = dict(
            volume_backend_name='volume_backend_name',
            vendor_name='Microsoft',
            driver_version=self._driver.VERSION,
            storage_protocol='iSCSI',
            total_capacity_gb=mock.sentinel.size_gb,
            free_capacity_gb=mock.sentinel.free_space_gb,
            reserved_percentage=10,
            QoS_support=False)

        self._driver._update_volume_stats()
        self.assertEqual(expected_volume_stats,
                         self._driver._stats)

    def test_extend_volume(self):
        volume = fake_volume.fake_volume_obj(mock.sentinel.fake_context)
        new_size_gb = 2
        expected_additional_sz_mb = 1024

        self._driver.extend_volume(volume, new_size_gb)

        self._driver._tgt_utils.extend_wt_disk.assert_called_once_with(
            volume.name, expected_additional_sz_mb)
