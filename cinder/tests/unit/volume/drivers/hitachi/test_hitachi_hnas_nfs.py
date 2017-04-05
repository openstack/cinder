# Copyright (c) 2014 Hitachi Data Systems, Inc.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
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
#

import mock
import os

from oslo_concurrency import processutils as putils
import socket

from cinder import context
from cinder import exception
from cinder.image import image_utils
from cinder import test
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder import utils
from cinder.volume import configuration as conf
from cinder.volume.drivers.hitachi import hnas_backend as backend
from cinder.volume.drivers.hitachi import hnas_nfs as nfs
from cinder.volume.drivers.hitachi import hnas_utils
from cinder.volume.drivers import nfs as base_nfs
from cinder.volume import utils as vutils

_VOLUME = {'name': 'cinder-volume',
           'id': fake.VOLUME_ID,
           'size': 128,
           'host': 'host1@hnas-nfs-backend#default',
           'volume_type': 'default',
           'provider_location': 'hnas'}

_SNAPSHOT = {
    'name': 'snapshot-51dd4-8d8a-4aa9-9176-086c9d89e7fc',
    'id': fake.SNAPSHOT_ID,
    'size': 128,
    'volume_type': None,
    'provider_location': 'hnas',
    'volume_size': 128,
    'volume': _VOLUME,
    'volume_name': _VOLUME['name'],
    'host': 'host1@hnas-iscsi-backend#silver',
    'volume_type_id': fake.VOLUME_TYPE_ID,
}


class HNASNFSDriverTest(test.TestCase):
    """Test HNAS NFS volume driver."""

    def __init__(self, *args, **kwargs):
        super(HNASNFSDriverTest, self).__init__(*args, **kwargs)

    def instantiate_snapshot(self, snap):
        snap = snap.copy()
        snap['volume'] = fake_volume.fake_volume_obj(
            None, **snap['volume'])
        snapshot = fake_snapshot.fake_snapshot_obj(
            None, expected_attrs=['volume'], **snap)
        return snapshot

    def setUp(self):
        super(HNASNFSDriverTest, self).setUp()
        self.context = context.get_admin_context()

        self.volume = fake_volume.fake_volume_obj(
            self.context,
            **_VOLUME)

        self.snapshot = self.instantiate_snapshot(_SNAPSHOT)

        self.volume_type = fake_volume.fake_volume_type_obj(
            None,
            **{'name': 'silver'}
        )
        self.clone = fake_volume.fake_volume_obj(
            None,
            **{'id': fake.VOLUME2_ID,
               'size': 128,
               'host': 'host1@hnas-nfs-backend#default',
               'volume_type': 'default',
               'provider_location': 'hnas'})

        # xml parsed from utils
        self.parsed_xml = {
            'username': 'supervisor',
            'password': 'supervisor',
            'hnas_cmd': 'ssc',
            'ssh_port': '22',
            'services': {
                'default': {
                    'hdp': '172.24.49.21:/fs-cinder',
                    'pool_name': 'default',
                    'label': 'svc_0',
                    'ctl': '1',
                    'export': {
                        'fs': 'fs-cinder',
                        'path': '/export-cinder/volume'
                    }
                },
            },
            'cluster_admin_ip0': None,
            'ssh_private_key': None,
            'chap_enabled': 'True',
            'mgmt_ip0': '172.17.44.15',
            'ssh_enabled': None
        }

        self.configuration = mock.Mock(spec=conf.Configuration)
        self.configuration.hds_hnas_nfs_config_file = 'fake.xml'

        self.mock_object(hnas_utils, 'read_cinder_conf',
                         return_value=self.parsed_xml)

        self.configuration = mock.Mock(spec=conf.Configuration)
        self.configuration.max_over_subscription_ratio = 20.0
        self.configuration.reserved_percentage = 0
        self.configuration.hds_hnas_nfs_config_file = 'fake_config.xml'
        self.configuration.nfs_shares_config = 'fake_nfs_share.xml'
        self.configuration.num_shell_tries = 2
        self.configuration.nfs_mount_point_base = '%state_path/mnt'
        self.configuration.nfs_mount_options = None

        self.driver = nfs.HNASNFSDriver(configuration=self.configuration)

    def test_check_pool_and_share_no_default_configured(self):
        nfs_shares = '172.24.49.21:/fs-cinder'

        self.mock_object(hnas_utils, 'get_pool', return_value='default')

        self.driver.config['services'] = {
            'silver': {
                'hdp': 'fs3',
                'iscsi_ip': '172.17.39.133',
                'iscsi_port': '3260',
                'port': '22',
                'volume_type': 'silver',
                'label': 'svc_1',
                'evs': '2',
                'tgt': {
                    'alias': 'iscsi-test',
                    'secret': 'itEpgB5gPefGhW2'
                }
            }
        }

        self.assertRaises(exception.ManageExistingVolumeTypeMismatch,
                          self.driver._check_pool_and_share, self.volume,
                          nfs_shares)

    def test_check_pool_and_share_mismatch_exception(self):
        # passing a share that does not exists in config should raise an
        # exception
        nfs_shares = '172.24.49.21:/nfs_share'

        self.mock_object(hnas_utils, 'get_pool', return_value='default')

        self.assertRaises(exception.ManageExistingVolumeTypeMismatch,
                          self.driver._check_pool_and_share, self.volume,
                          nfs_shares)

    def test_check_pool_and_share_type_mismatch_exception(self):
        nfs_shares = '172.24.49.21:/fs-cinder'
        self.volume.host = 'host1@hnas-nfs-backend#gold'

        # returning a pool different from 'default' should raise an exception
        self.mock_object(hnas_utils, 'get_pool', return_value='default')

        self.assertRaises(exception.ManageExistingVolumeTypeMismatch,
                          self.driver._check_pool_and_share, self.volume,
                          nfs_shares)

    def test_do_setup(self):
        version_info = {
            'mac': '83-68-96-AA-DA-5D',
            'model': 'HNAS 4040',
            'version': '12.4.3924.11',
            'hardware': 'NAS Platform',
            'serial': 'B1339109',
        }
        export_list = [
            {'fs': 'fs-cinder',
             'name': '/fs-cinder',
             'free': 228.0,
             'path': '/fs-cinder',
             'evs': ['172.24.49.21'],
             'size': 250.0}
        ]

        showmount = "Export list for 172.24.49.21:                  \n\
/fs-cinder                                 *                        \n\
/shares/9bcf0bcc-8cc8-437e38bcbda9 127.0.0.1,10.1.0.5,172.24.44.141 \n\
"

        self.mock_object(backend.HNASSSHBackend, 'get_version',
                         return_value=version_info)
        self.mock_object(self.driver, '_load_shares_config')
        self.mock_object(backend.HNASSSHBackend, 'get_export_list',
                         return_value=export_list)
        self.mock_object(self.driver, '_execute', return_value=(showmount, ''))

        self.driver.do_setup(None)

        self.driver._execute.assert_called_with('showmount', '-e',
                                                '172.24.49.21')
        self.assertTrue(backend.HNASSSHBackend.get_export_list.called)

    def test_do_setup_execute_exception(self):
        version_info = {
            'mac': '83-68-96-AA-DA-5D',
            'model': 'HNAS 4040',
            'version': '12.4.3924.11',
            'hardware': 'NAS Platform',
            'serial': 'B1339109',
        }

        export_list = [
            {'fs': 'fs-cinder',
             'name': '/fs-cinder',
             'free': 228.0,
             'path': '/fs-cinder',
             'evs': ['172.24.49.21'],
             'size': 250.0}
        ]

        self.mock_object(backend.HNASSSHBackend, 'get_version',
                         return_value=version_info)
        self.mock_object(self.driver, '_load_shares_config')
        self.mock_object(backend.HNASSSHBackend, 'get_export_list',
                         return_value=export_list)
        self.mock_object(self.driver, '_execute',
                         side_effect=putils.ProcessExecutionError)

        self.assertRaises(putils.ProcessExecutionError, self.driver.do_setup,
                          None)

    def test_do_setup_missing_export(self):
        version_info = {
            'mac': '83-68-96-AA-DA-5D',
            'model': 'HNAS 4040',
            'version': '12.4.3924.11',
            'hardware': 'NAS Platform',
            'serial': 'B1339109',
        }
        export_list = [
            {'fs': 'fs-cinder',
             'name': '/wrong-fs',
             'free': 228.0,
             'path': '/fs-cinder',
             'evs': ['172.24.49.21'],
             'size': 250.0}
        ]

        showmount = "Export list for 172.24.49.21:                  \n\
/fs-cinder                                 *                        \n\
"

        self.mock_object(backend.HNASSSHBackend, 'get_version',
                         return_value=version_info)
        self.mock_object(self.driver, '_load_shares_config')
        self.mock_object(backend.HNASSSHBackend, 'get_export_list',
                         return_value=export_list)
        self.mock_object(self.driver, '_execute', return_value=(showmount, ''))

        self.assertRaises(exception.InvalidParameterValue,
                          self.driver.do_setup, None)

    def test_create_volume(self):
        self.mock_object(self.driver, '_ensure_shares_mounted')
        self.mock_object(self.driver, '_do_create_volume')

        out = self.driver.create_volume(self.volume)

        self.assertEqual('172.24.49.21:/fs-cinder', out['provider_location'])
        self.assertTrue(self.driver._ensure_shares_mounted.called)

    def test_create_volume_exception(self):
        # pool 'original' doesnt exists in services
        self.volume.host = 'host1@hnas-nfs-backend#original'

        self.mock_object(self.driver, '_ensure_shares_mounted')

        self.assertRaises(exception.ParameterNotFound,
                          self.driver.create_volume, self.volume)

    def test_create_cloned_volume(self):
        self.volume.size = 150

        self.mock_object(self.driver, 'extend_volume')
        self.mock_object(backend.HNASSSHBackend, 'file_clone')

        out = self.driver.create_cloned_volume(self.volume, self.clone)

        self.assertEqual('hnas', out['provider_location'])

    def test_create_cloned_volume_invalid_volume_type(self):
        self.volume.volume_type_id = fake.VOLUME_TYPE_ID
        self.clone.volume_type_id = fake.VOLUME_TYPE2_ID

        self.mock_object(self.driver, 'extend_volume')
        self.mock_object(backend.HNASSSHBackend, 'file_clone')

        self.assertRaises(exception.InvalidVolumeType,
                          self.driver.create_cloned_volume, self.volume,
                          self.clone)

    def test_get_volume_stats(self):
        self.driver.pools = [{'pool_name': 'default',
                              'service_label': 'default',
                              'fs': '172.24.49.21:/easy-stack'},
                             {'pool_name': 'cinder_svc',
                              'service_label': 'cinder_svc',
                              'fs': '172.24.49.26:/MNT-CinderTest2'}]

        self.mock_object(self.driver, '_update_volume_stats')
        self.mock_object(self.driver, '_get_capacity_info',
                         return_value=(150, 50, 100))

        out = self.driver.get_volume_stats()

        self.assertEqual('6.0.0', out['driver_version'])
        self.assertEqual('Hitachi', out['vendor_name'])
        self.assertEqual('NFS', out['storage_protocol'])

    def test_create_volume_from_snapshot(self):
        expected_out = {'provider_location': 'hnas'}

        self.mock_object(self.driver, '_file_not_present',
                         mock.Mock(return_value=False))
        self.mock_object(backend.HNASSSHBackend, 'file_clone')
        result = self.driver.create_volume_from_snapshot(self.volume,
                                                         self.snapshot)

        self.assertEqual(expected_out, result)

    def test_create_volume_from_snapshot_legacy(self):
        expected_out = {'provider_location': 'hnas'}

        self.mock_object(self.driver, '_file_not_present',
                         mock.Mock(return_value=True))
        self.mock_object(backend.HNASSSHBackend, 'file_clone')
        result = self.driver.create_volume_from_snapshot(self.volume,
                                                         self.snapshot)

        self.assertEqual(expected_out, result)

    def test_create_snapshot(self):
        expected_out = {'provider_location': 'hnas'}
        self.mock_object(backend.HNASSSHBackend, 'file_clone')
        result = self.driver.create_snapshot(self.snapshot)

        self.assertEqual(expected_out, result)

    def test_delete_snapshot(self):
        nfs_mount = "/opt/stack/data/cinder/mnt/"
        path = nfs_mount + self.driver._get_snapshot_name(self.snapshot)

        self.mock_object(self.driver, '_file_not_present',
                         mock.Mock(return_value=False))

        self.mock_object(self.driver, '_get_file_path',
                         mock.Mock(return_value=path))
        self.mock_object(self.driver, '_execute')

        self.driver.delete_snapshot(self.snapshot)

        self.driver._execute.assert_called_with('rm', path, run_as_root=True)

    def test_delete_snapshot_legacy(self):
        nfs_mount = "/opt/stack/data/cinder/mnt/"
        legacy_path = nfs_mount + self.snapshot.name

        self.mock_object(self.driver, '_file_not_present',
                         mock.Mock(return_value=True))
        self.mock_object(self.driver, '_file_not_present',
                         mock.Mock(return_value=False))
        self.mock_object(self.driver, '_get_file_path',
                         mock.Mock(return_value=legacy_path))
        self.mock_object(self.driver, '_execute')

        self.driver.delete_snapshot(self.snapshot)

        self.driver._execute.assert_called_with('rm', legacy_path,
                                                run_as_root=True)

    def test_extend_volume(self):
        share_mount_point = '/fs-cinder'
        data = image_utils.imageutils.QemuImgInfo
        data.virtual_size = 200 * 1024 ** 3

        self.mock_object(self.driver, '_get_mount_point_for_share',
                         return_value=share_mount_point)
        self.mock_object(image_utils, 'qemu_img_info', return_value=data)

        self.driver.extend_volume(self.volume, 200)

        self.driver._get_mount_point_for_share.assert_called_with('hnas')

    def test_extend_volume_resizing_exception(self):
        share_mount_point = '/fs-cinder'
        data = image_utils.imageutils.QemuImgInfo
        data.virtual_size = 2048 ** 3

        self.mock_object(self.driver, '_get_mount_point_for_share',
                         return_value=share_mount_point)
        self.mock_object(image_utils, 'qemu_img_info', return_value=data)

        self.mock_object(image_utils, 'resize_image')

        self.assertRaises(exception.InvalidResults,
                          self.driver.extend_volume, self.volume, 200)

    def test_manage_existing(self):
        self.driver._mounted_shares = ['172.24.49.21:/fs-cinder']
        existing_vol_ref = {'source-name': '172.24.49.21:/fs-cinder'}

        self.mock_object(os.path, 'isfile', return_value=True)
        self.mock_object(self.driver, '_get_mount_point_for_share',
                         return_value='/fs-cinder/cinder-volume')
        self.mock_object(utils, 'resolve_hostname',
                         return_value='172.24.49.21')
        self.mock_object(self.driver, '_ensure_shares_mounted')
        self.mock_object(self.driver, '_execute')

        out = self.driver.manage_existing(self.volume, existing_vol_ref)

        loc = {'provider_location': '172.24.49.21:/fs-cinder'}
        self.assertEqual(loc, out)

        os.path.isfile.assert_called_once_with('/fs-cinder/cinder-volume/')
        self.driver._get_mount_point_for_share.assert_called_once_with(
            '172.24.49.21:/fs-cinder')
        utils.resolve_hostname.assert_called_with('172.24.49.21')
        self.driver._ensure_shares_mounted.assert_called_once_with()

    def test_manage_existing_name_matches(self):
        self.driver._mounted_shares = ['172.24.49.21:/fs-cinder']
        existing_vol_ref = {'source-name': '172.24.49.21:/fs-cinder'}

        self.mock_object(self.driver, '_get_share_mount_and_vol_from_vol_ref',
                         return_value=('172.24.49.21:/fs-cinder',
                                       '/mnt/silver',
                                       self.volume.name))

        out = self.driver.manage_existing(self.volume, existing_vol_ref)

        loc = {'provider_location': '172.24.49.21:/fs-cinder'}
        self.assertEqual(loc, out)

    def test_manage_existing_exception(self):
        existing_vol_ref = {'source-name': '172.24.49.21:/fs-cinder'}

        self.mock_object(self.driver, '_get_share_mount_and_vol_from_vol_ref',
                         return_value=('172.24.49.21:/fs-cinder',
                                       '/mnt/silver',
                                       'cinder-volume'))
        self.mock_object(self.driver, '_execute',
                         side_effect=putils.ProcessExecutionError)

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.manage_existing, self.volume,
                          existing_vol_ref)

    def test_manage_existing_missing_source_name(self):
        # empty source-name should raise an exception
        existing_vol_ref = {}

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing, self.volume,
                          existing_vol_ref)

    def test_manage_existing_already_managed(self):
        self.driver._mounted_shares = ['172.24.49.21:/fs-cinder']
        existing_vol_ref = {'source-name': '172.24.49.21:/fs-cinder'}
        expected_size = 1

        self.mock_object(self.driver, '_ensure_shares_mounted')
        self.mock_object(base_nfs.NfsDriver, '_get_mount_point_for_share',
                         return_value='/mnt/silver')
        self.mock_object(os.path, 'isfile', return_value=True)
        self.mock_object(utils, 'get_file_size', return_value=expected_size)

        self.mock_object(vutils, 'check_already_managed_volume',
                         return_value=True)

        self.assertRaises(exception.ManageExistingAlreadyManaged,
                          self.driver.manage_existing, self.volume,
                          existing_vol_ref)

    def test_manage_existing_missing_volume_in_backend(self):
        self.driver._mounted_shares = ['172.24.49.21:/fs-cinder']
        existing_vol_ref = {'source-name': '172.24.49.21:/fs-cinder'}

        self.mock_object(self.driver, '_ensure_shares_mounted')
        self.mock_object(utils, 'resolve_hostname',
                         side_effect=['172.24.49.21', '172.24.49.22'])

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing, self.volume,
                          existing_vol_ref)

    def test_manage_existing_get_size(self):
        existing_vol_ref = {
            'source-name': '172.24.49.21:/fs-cinder/cinder-volume',
        }
        self.driver._mounted_shares = ['172.24.49.21:/fs-cinder']
        expected_size = 1

        self.mock_object(self.driver, '_ensure_shares_mounted')
        self.mock_object(utils, 'resolve_hostname',
                         return_value='172.24.49.21')
        self.mock_object(base_nfs.NfsDriver, '_get_mount_point_for_share',
                         return_value='/mnt/silver')
        self.mock_object(os.path, 'isfile', return_value=True)
        self.mock_object(utils, 'get_file_size', return_value=expected_size)

        out = self.driver.manage_existing_get_size(self.volume,
                                                   existing_vol_ref)

        self.assertEqual(1, out)
        utils.get_file_size.assert_called_once_with(
            '/mnt/silver/cinder-volume')
        utils.resolve_hostname.assert_called_with('172.24.49.21')

    def test_manage_existing_get_size_exception(self):
        existing_vol_ref = {
            'source-name': '172.24.49.21:/fs-cinder/cinder-volume',
        }
        self.driver._mounted_shares = ['172.24.49.21:/fs-cinder']

        self.mock_object(self.driver, '_get_share_mount_and_vol_from_vol_ref',
                         return_value=('172.24.49.21:/fs-cinder',
                                       '/mnt/silver',
                                       'cinder-volume'))

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.manage_existing_get_size, self.volume,
                          existing_vol_ref)

    def test_manage_existing_get_size_resolving_hostname_exception(self):
        existing_vol_ref = {
            'source-name': '172.24.49.21:/fs-cinder/cinder-volume',
        }

        self.driver._mounted_shares = ['172.24.49.21:/fs-cinder']

        self.mock_object(self.driver, '_ensure_shares_mounted')
        self.mock_object(utils, 'resolve_hostname',
                         side_effect=socket.gaierror)

        self.assertRaises(socket.gaierror,
                          self.driver.manage_existing_get_size, self.volume,
                          existing_vol_ref)

    def test_unmanage(self):
        path = '/opt/stack/cinder/mnt/826692dfaeaf039b1f4dcc1dacee2c2e'
        vol_str = 'volume-' + self.volume.id
        vol_path = os.path.join(path, vol_str)
        new_path = os.path.join(path, 'unmanage-' + vol_str)

        self.mock_object(self.driver, '_get_mount_point_for_share',
                         return_value=path)
        self.mock_object(self.driver, '_execute')

        self.driver.unmanage(self.volume)

        self.driver._execute.assert_called_with('mv', vol_path, new_path,
                                                run_as_root=False,
                                                check_exit_code=True)
        self.driver._get_mount_point_for_share.assert_called_with(
            self.volume.provider_location)

    def test_unmanage_volume_exception(self):
        path = '/opt/stack/cinder/mnt/826692dfaeaf039b1f4dcc1dacee2c2e'

        self.mock_object(self.driver, '_get_mount_point_for_share',
                         return_value=path)
        self.mock_object(self.driver, '_execute', side_effect=ValueError)

        self.driver.unmanage(self.volume)

    def test_manage_existing_snapshot(self):
        nfs_share = "172.24.49.21:/fs-cinder"
        nfs_mount = "/opt/stack/data/cinder/mnt/" + fake.SNAPSHOT_ID
        path = "unmanage-%s.%s" % (self.snapshot.volume.name, self.snapshot.id)
        loc = {'provider_location': '172.24.49.21:/fs-cinder'}
        existing_ref = {'source-name': '172.24.49.21:/fs-cinder/'
                                       + fake.SNAPSHOT_ID}

        self.mock_object(self.driver, '_get_share_mount_and_vol_from_vol_ref',
                         return_value=(nfs_share, nfs_mount, path))
        self.mock_object(backend.HNASSSHBackend, 'check_snapshot_parent',
                         return_value=True)
        self.mock_object(self.driver, '_execute')
        self.mock_object(backend.HNASSSHBackend, 'get_export_path',
                         return_value='fs-cinder')

        out = self.driver.manage_existing_snapshot(self.snapshot,
                                                   existing_ref)

        self.assertEqual(loc, out)

    def test_manage_existing_snapshot_legacy(self):
        nfs_share = "172.24.49.21:/fs-cinder"
        nfs_mount = "/opt/stack/data/cinder/mnt/" + fake.SNAPSHOT_ID
        path = "unmanage-snapshot-%s" % self.snapshot.id
        loc = {'provider_location': '172.24.49.21:/fs-cinder'}
        existing_ref = {
            'source-name': '172.24.49.21:/fs-cinder/' + fake.SNAPSHOT_ID}

        self.mock_object(self.driver, '_get_share_mount_and_vol_from_vol_ref',
                         return_value=(nfs_share, nfs_mount, path))
        self.mock_object(backend.HNASSSHBackend, 'check_snapshot_parent',
                         return_value=True)
        self.mock_object(self.driver, '_execute')
        self.mock_object(backend.HNASSSHBackend, 'get_export_path',
                         return_value='fs-cinder')

        out = self.driver.manage_existing_snapshot(self.snapshot, existing_ref)

        self.assertEqual(loc, out)

    def test_manage_existing_snapshot_not_parent_exception(self):
        nfs_share = "172.24.49.21:/fs-cinder"
        nfs_mount = "/opt/stack/data/cinder/mnt/" + fake.SNAPSHOT_ID
        path = "unmanage-%s.%s" % (fake.VOLUME_ID, self.snapshot.id)

        existing_ref = {'source-name': '172.24.49.21:/fs-cinder/'
                                       + fake.SNAPSHOT_ID}

        self.mock_object(self.driver, '_get_share_mount_and_vol_from_vol_ref',
                         return_value=(nfs_share, nfs_mount, path))
        self.mock_object(backend.HNASSSHBackend, 'check_snapshot_parent',
                         return_value=False)
        self.mock_object(backend.HNASSSHBackend, 'get_export_path',
                         return_value='fs-cinder')

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot, self.snapshot,
                          existing_ref)

    def test_manage_existing_snapshot_get_size(self):
        existing_ref = {
            'source-name': '172.24.49.21:/fs-cinder/cinder-snapshot',
        }
        self.driver._mounted_shares = ['172.24.49.21:/fs-cinder']
        expected_size = 1

        self.mock_object(self.driver, '_ensure_shares_mounted')
        self.mock_object(utils, 'resolve_hostname',
                         return_value='172.24.49.21')
        self.mock_object(base_nfs.NfsDriver, '_get_mount_point_for_share',
                         return_value='/mnt/silver')
        self.mock_object(os.path, 'isfile', return_value=True)
        self.mock_object(utils, 'get_file_size', return_value=expected_size)

        out = self.driver.manage_existing_snapshot_get_size(
            self.snapshot, existing_ref)

        self.assertEqual(1, out)
        utils.get_file_size.assert_called_once_with(
            '/mnt/silver/cinder-snapshot')
        utils.resolve_hostname.assert_called_with('172.24.49.21')

    def test_unmanage_snapshot(self):
        path = '/opt/stack/cinder/mnt/826692dfaeaf039b1f4dcc1dacee2c2e'
        snapshot_name = "%s.%s" % (self.snapshot.volume.name, self.snapshot.id)
        old_path = os.path.join(path, snapshot_name)
        new_path = os.path.join(path, 'unmanage-' + snapshot_name)

        self.mock_object(self.driver, '_get_mount_point_for_share',
                         return_value=path)
        self.mock_object(self.driver, '_execute')

        self.driver.unmanage_snapshot(self.snapshot)

        self.driver._execute.assert_called_with('mv', old_path, new_path,
                                                run_as_root=False,
                                                check_exit_code=True)
        self.driver._get_mount_point_for_share.assert_called_with(
            self.snapshot.provider_location)

    def test_get_manageable_volumes_not_safe(self):
        manageable_vol = [{'cinder_id': '1e5177e7-95e5-4a0f-b170-e45f4b469f6a',
                           'extra_info': None,
                           'reason_not_safe': 'already managed',
                           'reference': {
                               'source-name':
                                   '172.24.49.21:/fs-cinder/volume-1e5177e7-'
                                   '95e5-4a0f-b170-e45f4b469f6a'},
                           'safe_to_manage': False,
                           'size': 128}]

        rsrc = [self.volume]
        path = '/opt/stack/cinder/mnt/826692dfaeaf039b1f4dcc1dacee2c2e'
        self.mock_object(base_nfs.NfsDriver, '_get_mount_point_for_share',
                         return_value=path)
        vols_exp = [self.volume.name]
        self.mock_object(self.driver, '_get_volumes_from_export',
                         return_value=vols_exp)
        self.mock_object(self.driver, '_get_file_size',
                         return_value=self.volume.size)

        out = self.driver._get_manageable_resource_info(
            rsrc, "volume", None, 1000, 0, ['reference'], ['desc'])

        self.driver._get_volumes_from_export.assert_called_with(
            '172.24.49.21:/fs-cinder')
        self.driver._get_file_size.assert_called_with('%s/%s' % (
            path, self.volume.name))
        self.driver._get_mount_point_for_share(self.volume.provider_location)

        self.assertEqual(out, manageable_vol)

    def test_get_manageable_volumes(self):
        manageable_vol = [{
            'cinder_id': '1e5177e7-95e5-4a0f-b170-e45f4b469f6a',
            'extra_info': None,
            'reason_not_safe': 'already managed',
            'reference': {
                'source-name': '172.24.49.21:/fs-cinder/'
                               'volume-1e5177e7-95e5-4a0f-b170-e45f4b469f6a'},
            'safe_to_manage': False,
            'size': 128}]

        rsrc = [self.volume]
        path = '/opt/stack/cinder/mnt/826692dfaeaf039b1f4dcc1dacee2c2e'
        self.mock_object(base_nfs.NfsDriver, '_get_mount_point_for_share',
                         return_value=path)
        vols_exp = [fake.VOLUME_NAME]
        self.mock_object(self.driver, '_get_volumes_from_export',
                         return_value=vols_exp)
        self.mock_object(self.driver, '_get_file_size',
                         return_value=self.volume.size)

        out = self.driver._get_manageable_resource_info(rsrc, "volume", None,
                                                        1000, 0, ['reference'],
                                                        ['desc'])

        self.driver._get_volumes_from_export.assert_called_with(
            '172.24.49.21:/fs-cinder')
        self.driver._get_file_size.assert_called_with(
            '%s/%s' % (path, self.volume.name))
        self.driver._get_mount_point_for_share(self.volume.provider_location)

        self.assertEqual(out, manageable_vol)

    def test_get_manageable_snapshots(self):
        manageable_snap = [{
            'cinder_id': '253b2878-ec60-4793-ad19-e65496ec7aab',
            'extra_info': None,
            'reason_not_safe': 'already managed',
            'reference': {
                'source-name': '172.24.49.21:/fs-cinder/'
                               'snapshot-253b2878-ec60-4793-'
                               'ad19-e65496ec7aab'},
            'safe_to_manage': False,
            'size': 128,
            'source_reference': {'id': '1'}}]

        rsrc = [self.snapshot]
        path = '/opt/stack/cinder/mnt/826692dfaeaf039b1f4dcc1dacee2c2e'
        self.mock_object(base_nfs.NfsDriver, '_get_mount_point_for_share',
                         return_value=path)
        vols_exp = [fake.SNAPSHOT_NAME]
        self.mock_object(self.driver, '_get_volumes_from_export',
                         return_value=vols_exp)
        self.mock_object(self.driver, '_get_file_size',
                         return_value=self.volume.size)
        self.mock_object(backend.HNASSSHBackend, 'get_cloned_file_relatives',
                         return_value=[' /nfs_cinder/volume-1',
                                       '/nfs_cinder/snapshot2'])

        out = self.driver._get_manageable_resource_info(rsrc, "snapshot", None,
                                                        1000, 0, ['reference'],
                                                        ['desc'])

        self.driver._get_volumes_from_export.assert_called_with(
            '172.24.49.21:/fs-cinder')
        self.driver._get_file_size.assert_called_with(
            '%s/%s' % (path, self.snapshot.name))
        self.driver._get_mount_point_for_share(self.snapshot.provider_location)

        self.assertEqual(out, manageable_snap)

    def test_get_manageable_snapshots_unknown_origin(self):
        manageable_snap = [{
            'cinder_id': '253b2878-ec60-4793-ad19-e65496ec7aab',
            'extra_info': 'Could not determine the volume that owns '
                          'the snapshot',
            'reason_not_safe': 'already managed',
            'reference': {
                'source-name': '172.24.49.21:/fs-cinder/'
                               'snapshot-253b2878-ec60-4793-'
                               'ad19-e65496ec7aab'},
            'safe_to_manage': False,
            'size': 128,
            'source_reference': {'id': 'unknown'}}]

        rsrc = [self.snapshot]
        path = '/opt/stack/cinder/mnt/826692dfaeaf039b1f4dcc1dacee2c2e'
        self.mock_object(base_nfs.NfsDriver, '_get_mount_point_for_share',
                         return_value=path)
        vols_exp = [fake.SNAPSHOT_NAME]
        self.mock_object(self.driver, '_get_volumes_from_export',
                         return_value=vols_exp)
        self.mock_object(self.driver, '_get_file_size',
                         return_value=self.volume.size)
        self.mock_object(backend.HNASSSHBackend, 'get_cloned_file_relatives',
                         return_value=[' /nfs_cinder/volume-1',
                                       ' /nfs_cinder/volume-2',
                                       '/nfs_cinder/snapshot2'])

        out = self.driver._get_manageable_resource_info(rsrc, "snapshot", None,
                                                        1000, 0, ['reference'],
                                                        ['desc'])

        self.driver._get_volumes_from_export.assert_called_with(
            '172.24.49.21:/fs-cinder')
        self.driver._get_mount_point_for_share(self.snapshot.provider_location)
        self.driver._get_file_size.assert_called_with('%s/%s' % (
            path, self.snapshot.name))
        self.assertEqual(out, manageable_snap)
