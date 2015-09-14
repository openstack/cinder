# Copyright (c) 2014 Andrew Kerr.  All rights reserved.
# Copyright (c) 2015 Tom Barron.  All rights reserved.
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
Mock unit tests for the NetApp cmode nfs storage driver
"""

import mock
from oslo_utils import units

from cinder.brick.remotefs import remotefs as remotefs_brick
from cinder import test
from cinder.tests.volume.drivers.netapp.dataontap import fakes as fake
from cinder.tests.volume.drivers.netapp import fakes as na_fakes
from cinder import utils
from cinder.volume.drivers.netapp.dataontap.client import client_cmode
from cinder.volume.drivers.netapp.dataontap import nfs_base
from cinder.volume.drivers.netapp.dataontap import nfs_cmode
from cinder.volume.drivers.netapp import utils as na_utils
from cinder.volume.drivers import nfs


class NetAppCmodeNfsDriverTestCase(test.TestCase):
    def setUp(self):
        super(NetAppCmodeNfsDriverTestCase, self).setUp()

        kwargs = {'configuration': self.get_config_cmode()}

        with mock.patch.object(utils, 'get_root_helper',
                               return_value=mock.Mock()):
            with mock.patch.object(remotefs_brick, 'RemoteFsClient',
                                   return_value=mock.Mock()):
                self.driver = nfs_cmode.NetAppCmodeNfsDriver(**kwargs)
                self.driver._mounted_shares = [fake.NFS_SHARE]
                self.driver.ssc_vols = True

    def get_config_cmode(self):
        config = na_fakes.create_configuration_cmode()
        config.netapp_storage_protocol = 'nfs'
        config.netapp_login = 'admin'
        config.netapp_password = 'pass'
        config.netapp_server_hostname = '127.0.0.1'
        config.netapp_transport_type = 'http'
        config.netapp_server_port = '80'
        config.netapp_vserver = 'openstack'
        return config

    @mock.patch.object(client_cmode, 'Client', mock.Mock())
    @mock.patch.object(nfs.NfsDriver, 'do_setup')
    @mock.patch.object(na_utils, 'check_flags')
    def test_do_setup(self, mock_check_flags, mock_super_do_setup):
        self.driver.do_setup(mock.Mock())

        self.assertTrue(mock_check_flags.called)
        self.assertTrue(mock_super_do_setup.called)

    def test_get_pool_stats(self):

        total_capacity_gb = na_utils.round_down(
            fake.TOTAL_BYTES / units.Gi, '0.01')
        free_capacity_gb = na_utils.round_down(
            fake.AVAILABLE_BYTES / units.Gi, '0.01')
        capacity = dict(
            reserved_percentage = fake.RESERVED_PERCENTAGE,
            total_capacity_gb = total_capacity_gb,
            free_capacity_gb = free_capacity_gb,
        )

        mock_get_capacity = self.mock_object(
            self.driver, '_get_share_capacity_info')
        mock_get_capacity.return_value = capacity

        mock_get_vol_for_share = self.mock_object(
            self.driver, '_get_vol_for_share')
        mock_get_vol_for_share.return_value = None

        result = self.driver._get_pool_stats()

        self.assertEqual(fake.RESERVED_PERCENTAGE,
                         result[0]['reserved_percentage'])
        self.assertEqual(total_capacity_gb, result[0]['total_capacity_gb'])
        self.assertEqual(free_capacity_gb, result[0]['free_capacity_gb'])

    def test_delete_volume(self):
        fake_provider_location = 'fake_provider_location'
        fake_volume = {'provider_location': fake_provider_location}
        self.mock_object(self.driver, '_delete_backing_file_for_volume')
        self.driver.zapi_client = mock.Mock()
        mock_prov_deprov = self.mock_object(self.driver,
                                            '_post_prov_deprov_in_ssc')

        self.driver.delete_volume(fake_volume)

        mock_prov_deprov.assert_called_once_with(fake_provider_location)

    def test_delete_volume_exception_path(self):
        fake_provider_location = 'fake_provider_location'
        fake_volume = {'provider_location': fake_provider_location}
        self.mock_object(self.driver, '_delete_backing_file_for_volume')
        self.driver.zapi_client = mock.Mock(side_effect=[Exception])
        mock_prov_deprov = self.mock_object(self.driver,
                                            '_post_prov_deprov_in_ssc')

        self.driver.delete_volume(fake_volume)

        mock_prov_deprov.assert_called_once_with(fake_provider_location)

    def test_delete_backing_file_for_volume(self):
        mock_filer_delete = self.mock_object(self.driver,
                                             '_delete_volume_on_filer')
        mock_super_delete = self.mock_object(nfs_base.NetAppNfsDriver,
                                             'delete_volume')

        self.driver._delete_backing_file_for_volume(fake.NFS_VOLUME)

        mock_filer_delete.assert_called_once_with(fake.NFS_VOLUME)
        self.assertEqual(0, mock_super_delete.call_count)

    def test_delete_backing_file_for_volume_exception_path(self):
        mock_filer_delete = self.mock_object(self.driver,
                                             '_delete_volume_on_filer')
        mock_filer_delete.side_effect = [Exception]
        mock_super_delete = self.mock_object(nfs_base.NetAppNfsDriver,
                                             'delete_volume')

        self.driver._delete_backing_file_for_volume(fake.NFS_VOLUME)

        mock_filer_delete.assert_called_once_with(fake.NFS_VOLUME)
        mock_super_delete.assert_called_once_with(fake.NFS_VOLUME)

    def test_delete_volume_on_filer(self):
        mock_get_vs_ip = self.mock_object(self.driver, '_get_export_ip_path')
        mock_get_vs_ip.return_value = (fake.VSERVER_NAME, '/%s' % fake.FLEXVOL)
        self.driver.zapi_client = mock.Mock()
        mock_zapi_delete = self.driver.zapi_client.delete_file

        self.driver._delete_volume_on_filer(fake.NFS_VOLUME)

        mock_zapi_delete.assert_called_once_with(
            '/vol/%s/%s' % (fake.FLEXVOL, fake.NFS_VOLUME['name']))

    def test_delete_snapshot(self):
        mock_get_location = self.mock_object(self.driver,
                                             '_get_provider_location')
        mock_get_location.return_value = fake.PROVIDER_LOCATION

        mock_delete_backing = self.mock_object(
            self.driver, '_delete_backing_file_for_snapshot')

        mock_prov_deprov = self.mock_object(self.driver,
                                            '_post_prov_deprov_in_ssc')

        self.driver.delete_snapshot(fake.test_snapshot)

        mock_delete_backing.assert_called_once_with(fake.test_snapshot)
        mock_prov_deprov.assert_called_once_with(fake.PROVIDER_LOCATION)

    def test_delete_backing_file_for_snapshot(self):
        mock_filer_delete = self.mock_object(
            self.driver, '_delete_snapshot_on_filer')
        mock_super_delete = self.mock_object(nfs_base.NetAppNfsDriver,
                                             'delete_snapshot')

        self.driver._delete_backing_file_for_snapshot(fake.test_snapshot)

        mock_filer_delete.assert_called_once_with(fake.test_snapshot)
        self.assertEqual(0, mock_super_delete.call_count)

    def test_delete_backing_file_for_snapshot_exception_path(self):
        mock_filer_delete = self.mock_object(
            self.driver, '_delete_snapshot_on_filer')
        mock_filer_delete.side_effect = [Exception]
        mock_super_delete = self.mock_object(nfs_base.NetAppNfsDriver,
                                             'delete_snapshot')

        self.driver._delete_backing_file_for_snapshot(fake.test_snapshot)

        mock_filer_delete.assert_called_once_with(fake.test_snapshot)
        mock_super_delete.assert_called_once_with(fake.test_snapshot)

    def test_delete_snapshot_on_filer(self):
        mock_get_vs_ip = self.mock_object(self.driver, '_get_export_ip_path')
        mock_get_vs_ip.return_value = (fake.VSERVER_NAME, '/%s' % fake.FLEXVOL)
        self.driver.zapi_client = mock.Mock()
        mock_zapi_delete = self.driver.zapi_client.delete_file

        self.driver._delete_snapshot_on_filer(fake.test_snapshot)

        mock_zapi_delete.assert_called_once_with(
            '/vol/%s/%s' % (fake.FLEXVOL, fake.test_snapshot['name']))

    def test_get_vol_for_share(self):
        fake_volume = fake.test_volume
        ssc_vols = {'all': {fake_volume}}

        with mock.patch.object(self.driver, 'ssc_vols', ssc_vols):
            result = self.driver._get_vol_for_share(fake.NFS_SHARE)

        self.assertEqual(fake.test_volume, result)

    def test_get_vol_for_share_no_ssc_vols(self):
        with mock.patch.object(self.driver, 'ssc_vols', None):
            self.assertIsNone(self.driver._get_vol_for_share(fake.NFS_SHARE))
