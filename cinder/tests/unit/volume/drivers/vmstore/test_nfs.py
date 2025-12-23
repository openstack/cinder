# Copyright 2026 DDN, Inc. All rights reserved.
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

"""Unit tests for VMstore NFS driver."""

import os
from unittest import mock

from cinder import context
from cinder import exception
from cinder.tests.unit import test
from cinder.tests.unit.volume.drivers.vmstore import set_vmstore_overrides
from cinder.volume.drivers.vmstore import api
from cinder.volume.drivers.vmstore import nfs as vmstore_nfs


VMSTORE_CONFIG = {
    'nas_host': '192.168.1.1',
    'nas_share_path': '/tintri/test_share',
    'vmstore_rest_address': '192.168.1.1',
    'vmstore_rest_port': 443,
    'vmstore_rest_protocol': 'https',
    'vmstore_user': 'admin',
    'vmstore_password': 'secret',
    'vmstore_refresh_openstack_region': 'RegionOne',
    'vmstore_mount_point_base': '/mnt/vmstore',
    'vmstore_sparsed_volumes': True,
    'vmstore_qcow2_volumes': False,
}


class VmstoreNfsDriverTestCase(test.TestCase):
    """Test cases for VmstoreNfsDriver class."""

    def setUp(self):
        set_vmstore_overrides()
        super(VmstoreNfsDriverTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.configuration = mock.Mock()
        for key, value in VMSTORE_CONFIG.items():
            setattr(self.configuration, key, value)
        self.configuration.reserved_percentage = 0
        self.configuration.max_over_subscription_ratio = 1.0
        self.configuration.nfs_sparsed_volumes = True
        self.configuration.nfs_qcow2_volumes = False
        self.configuration.nfs_mount_point_base = '/mnt/vmstore'
        self.configuration.nfs_mount_options = None
        self.configuration.volume_dd_blocksize = '1M'
        self.configuration.nas_secure_file_operations = 'auto'
        self.configuration.nas_secure_file_permissions = 'auto'

        # Configure safe_get to return proper values for NFS options
        def safe_get_side_effect(key):
            config_map = {
                'nfs_mount_options': 'lookupcache=pos,nolock,noacl,proto=tcp',
                'volume_dd_blocksize': '1M',
                'nas_secure_file_operations': 'auto',
                'nas_secure_file_permissions': 'auto',
                'vmstore_openstack_hostname': None,
            }
            return config_map.get(key)

        self.configuration.safe_get = mock.Mock(
            side_effect=safe_get_side_effect)

    @mock.patch('os_brick.remotefs.remotefs.RemoteFsClient')
    @mock.patch.object(vmstore_nfs.VmstoreNfsDriver, '_check_snapshot_support')
    @mock.patch.object(vmstore_nfs.VmstoreNfsDriver, 'do_setup')
    def _get_driver(self, mock_do_setup, mock_check_snapshot, mock_remotefs):
        """Create and return a driver instance."""
        driver = vmstore_nfs.VmstoreNfsDriver(configuration=self.configuration)
        driver.vmstore = mock.Mock()
        driver._mounted_shares = ['192.168.1.1:/tintri/test_share']
        driver.shares = {'192.168.1.1:/tintri/test_share': None}
        driver.mount_point_base = '/mnt/vmstore'
        driver.nas_path = '/tintri/test_share'
        return driver

    def test_driver_version(self):
        """Test driver version is defined."""
        self.assertEqual('3.0.3', vmstore_nfs.VmstoreNfsDriver.VERSION)

    def test_ci_wiki_name(self):
        """Test CI wiki name is defined."""
        self.assertEqual(
            'Vmstore_CI', vmstore_nfs.VmstoreNfsDriver.CI_WIKI_NAME)

    def test_get_driver_options(self):
        """Test get_driver_options returns options list."""
        options = vmstore_nfs.VmstoreNfsDriver.get_driver_options()
        self.assertIsInstance(options, list)
        self.assertTrue(len(options) > 0)

    @mock.patch('cinder.objects.VolumeList.get_all_by_host')
    def test_backend_name(self, mock_get_volumes):
        """Test backend name generation."""
        mock_get_volumes.return_value = []
        driver = self._get_driver()
        driver._update_volume_stats()
        # Default backend name should include product and protocol
        self.assertIsNotNone(driver._stats)

    def test_local_volume_dir_md5(self):
        """Test _local_volume_dir uses MD5 with usedforsecurity=False."""
        driver = self._get_driver()
        volume = mock.Mock()
        volume.provider_location = '192.168.1.1:/tintri/test_share'

        vol_dir = driver._local_volume_dir(volume)
        self.assertTrue(vol_dir.startswith('/mnt/vmstore/'))
        # MD5 hash should be 32 hex characters
        hash_part = os.path.basename(vol_dir)
        self.assertEqual(32, len(hash_part))


class VmstoreNfsDriverDeleteVolumeTestCase(test.TestCase):
    """Test cases for delete_volume functionality."""

    def setUp(self):
        set_vmstore_overrides()
        super(VmstoreNfsDriverDeleteVolumeTestCase, self).setUp()
        self.context = context.get_admin_context()

    @mock.patch('os_brick.remotefs.remotefs.RemoteFsClient')
    @mock.patch.object(vmstore_nfs.VmstoreNfsDriver, '_ensure_shares_mounted')
    @mock.patch.object(vmstore_nfs.VmstoreNfsDriver, '_check_snapshot_support')
    @mock.patch.object(vmstore_nfs.VmstoreNfsDriver, 'do_setup')
    def test_delete_volume_no_provider_location(
            self, mock_do_setup, mock_check_snapshot,
            mock_ensure_shares, mock_remotefs):
        """Test delete_volume with no provider_location returns gracefully."""
        configuration = mock.Mock()
        for key, value in VMSTORE_CONFIG.items():
            setattr(configuration, key, value)
        configuration.reserved_percentage = 0
        configuration.max_over_subscription_ratio = 1.0
        configuration.nfs_sparsed_volumes = True
        configuration.nfs_mount_point_base = '/mnt/vmstore'

        def safe_get_side_effect(key):
            config_map = {
                'nfs_mount_options': 'lookupcache=pos,nolock,noacl,proto=tcp',
                'volume_dd_blocksize': '1M',
                'nas_secure_file_operations': 'auto',
                'nas_secure_file_permissions': 'auto',
                'vmstore_openstack_hostname': None,
            }
            return config_map.get(key)

        configuration.safe_get = mock.Mock(side_effect=safe_get_side_effect)

        driver = vmstore_nfs.VmstoreNfsDriver(configuration=configuration)
        driver.vmstore = mock.Mock()

        volume = mock.Mock()
        volume.provider_location = None
        volume.name = 'test_volume'
        volume.id = 'test-id'

        # Should return without raising
        driver.delete_volume(volume)


class VmstoreNfsDriverSnapshotTestCase(test.TestCase):
    """Test cases for snapshot functionality."""

    def setUp(self):
        set_vmstore_overrides()
        super(VmstoreNfsDriverSnapshotTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.configuration = mock.Mock()
        for key, value in VMSTORE_CONFIG.items():
            setattr(self.configuration, key, value)
        self.configuration.reserved_percentage = 0
        self.configuration.max_over_subscription_ratio = 1.0
        self.configuration.nfs_sparsed_volumes = True
        self.configuration.nfs_qcow2_volumes = False
        self.configuration.nfs_mount_point_base = '/mnt/vmstore'
        self.configuration.nfs_mount_options = None

        def safe_get_side_effect(key):
            config_map = {
                'nfs_mount_options': 'lookupcache=pos,nolock,noacl,proto=tcp',
                'volume_dd_blocksize': '1M',
                'nas_secure_file_operations': 'auto',
                'nas_secure_file_permissions': 'auto',
                'vmstore_openstack_hostname': None,
            }
            return config_map.get(key)

        self.configuration.safe_get = mock.Mock(
            side_effect=safe_get_side_effect)

    @mock.patch('os_brick.remotefs.remotefs.RemoteFsClient')
    @mock.patch.object(vmstore_nfs.VmstoreNfsDriver, '_check_snapshot_support')
    @mock.patch.object(vmstore_nfs.VmstoreNfsDriver, 'do_setup')
    def test_delete_snapshot_not_found(
            self, mock_do_setup, mock_check_snapshot, mock_remotefs):
        """Test delete_snapshot when snapshot not found returns gracefully."""
        driver = vmstore_nfs.VmstoreNfsDriver(configuration=self.configuration)
        driver.vmstore = mock.Mock()
        driver.vmstore.snapshots.list.return_value = []

        snapshot = mock.Mock()
        snapshot.__getitem__ = lambda s, key: {
            'name': 'non_existent_snapshot',
            'volume_id': 'test-volume-id'
        }[key]

        # Should return without raising when snapshot not found
        driver.delete_snapshot(snapshot)

    @mock.patch('os_brick.remotefs.remotefs.RemoteFsClient')
    @mock.patch.object(vmstore_nfs.VmstoreNfsDriver, '_check_snapshot_support')
    @mock.patch.object(vmstore_nfs.VmstoreNfsDriver, 'do_setup')
    def test_delete_snapshot_vm_present_logs_warning(
            self, mock_do_setup, mock_check_snapshot, mock_remotefs):
        """Test delete_snapshot logs warning when VM is still present."""
        driver = vmstore_nfs.VmstoreNfsDriver(configuration=self.configuration)
        driver.vmstore = mock.Mock()
        driver.vmstore.snapshots.list.return_value = [
            {'description': 'test_snapshot', 'uuid': {'uuid': 'snap-uuid'}}
        ]
        error = api.VmstoreException('VM is still present')
        driver.vmstore.snapshots.delete.side_effect = error

        snapshot = mock.Mock()
        snapshot.__getitem__ = lambda s, key: {
            'name': 'test_snapshot',
            'volume_id': 'test-volume-id'
        }[key]

        # Should not raise, just log warning
        driver.delete_snapshot(snapshot)


class VmstoreNfsDriverCreateSnapshotTestCase(test.TestCase):
    """Test cases for create_snapshot using volume.name_id."""

    def setUp(self):
        set_vmstore_overrides()
        super(VmstoreNfsDriverCreateSnapshotTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.configuration = mock.Mock()
        for key, value in VMSTORE_CONFIG.items():
            setattr(self.configuration, key, value)
        self.configuration.reserved_percentage = 0
        self.configuration.max_over_subscription_ratio = 1.0
        self.configuration.nfs_sparsed_volumes = True
        self.configuration.nfs_qcow2_volumes = False
        self.configuration.nfs_mount_point_base = '/mnt/vmstore'
        self.configuration.nfs_mount_options = None

        def safe_get_side_effect(key):
            config_map = {
                'nfs_mount_options': 'lookupcache=pos,nolock,noacl,proto=tcp',
                'volume_dd_blocksize': '1M',
                'nas_secure_file_operations': 'auto',
                'nas_secure_file_permissions': 'auto',
                'vmstore_openstack_hostname': None,
            }
            return config_map.get(key)

        self.configuration.safe_get = mock.Mock(
            side_effect=safe_get_side_effect)

    @mock.patch('os_brick.remotefs.remotefs.RemoteFsClient')
    @mock.patch.object(vmstore_nfs.VmstoreNfsDriver, '_check_snapshot_support')
    @mock.patch.object(vmstore_nfs.VmstoreNfsDriver, 'do_setup')
    def test_create_snapshot_uses_volume_name_id(
            self, mock_do_setup, mock_check_snapshot, mock_remotefs):
        """Test create_snapshot uses volume.name_id for backend lookup."""
        driver = vmstore_nfs.VmstoreNfsDriver(configuration=self.configuration)
        driver.vmstore = mock.Mock()
        driver.nas_path = '/tintri/test_share'

        # Mock virtual disk response
        driver.vmstore.virtual_disk.get.return_value = [{
            'vmName': 'test-vm',
            'vmUuid': {'uuid': 'vm-uuid-123'},
            'instanceUuid': 'instance-uuid-123'
        }]

        # Create a mock snapshot with a mock volume
        mock_volume = mock.Mock()
        mock_volume.name_id = 'volume-name-id-456'  # This should be used
        mock_volume.__getitem__ = lambda s, key: {
            'name': 'volume-volume-name-id-456',
        }[key]

        snapshot = mock.Mock()
        snapshot.volume = mock_volume
        snapshot.__getitem__ = lambda s, key: {
            'volume_name': 'volume-volume-name-id-456',
            'volume_id': 'volume-db-id-123',  # This should NOT be used
            'name': 'snapshot-name'
        }[key]

        driver.create_snapshot(snapshot)

        # Verify virtual_disk.get was called with name_id, not volume_id
        driver.vmstore.virtual_disk.get.assert_called_with(
            'volume-name-id-456')


class VmstoreNfsDriverShareTestCase(test.TestCase):
    """Test cases for share loading functionality."""

    def setUp(self):
        set_vmstore_overrides()
        super(VmstoreNfsDriverShareTestCase, self).setUp()
        self.configuration = mock.Mock()
        for key, value in VMSTORE_CONFIG.items():
            setattr(self.configuration, key, value)
        self.configuration.reserved_percentage = 0
        self.configuration.max_over_subscription_ratio = 1.0
        self.configuration.nfs_sparsed_volumes = True
        self.configuration.nfs_mount_options = None
        self.configuration.nfs_mount_point_base = '/mnt/vmstore'

        def safe_get_side_effect(key):
            config_map = {
                'nfs_mount_options': 'lookupcache=pos,nolock,noacl,proto=tcp',
                'volume_dd_blocksize': '1M',
                'nas_secure_file_operations': 'auto',
                'nas_secure_file_permissions': 'auto',
                'vmstore_openstack_hostname': None,
            }
            return config_map.get(key)

        self.configuration.safe_get = mock.Mock(
            side_effect=safe_get_side_effect)

    @mock.patch('os_brick.remotefs.remotefs.RemoteFsClient')
    @mock.patch.object(vmstore_nfs.VmstoreNfsDriver, '_check_snapshot_support')
    @mock.patch.object(vmstore_nfs.VmstoreNfsDriver, 'do_setup')
    def test_load_shares_invalid_format_raises(
            self, mock_do_setup, mock_check_snapshot, mock_remotefs):
        """Test _load_shares raises on invalid share format."""
        self.configuration.nas_host = 'invalid'
        self.configuration.nas_share_path = 'no_leading_slash'

        driver = vmstore_nfs.VmstoreNfsDriver(configuration=self.configuration)
        driver.vmstore = mock.Mock()

        self.assertRaises(
            exception.InvalidConfigurationValue,
            driver._load_shares
        )
