# Copyright 2013 IBM Corp.
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
#
# Authors:
#    Nilesh Bhosale <nilesh.bhosale@in.ibm.com>
#    Sasikanth Eda <sasikanth.eda@in.ibm.com>

"""
Tests for the IBM NAS family (SONAS, Storwize V7000 Unified,
NAS based IBM GPFS Storage Systems).
"""

import mock
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import units

from cinder import context
from cinder import exception
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.ibm import ibmnas

LOG = logging.getLogger(__name__)

CONF = cfg.CONF


class FakeEnv(object):
    fields = {}

    def __setitem__(self, key, value):
        self.fields[key] = value

    def __getitem__(self, item):
        return self.fields[item]


class IBMNASDriverTestCase(test.TestCase):

    TEST_NFS_EXPORT = 'nfs-host1:/export'
    TEST_SIZE_IN_GB = 1
    TEST_EXTEND_SIZE_IN_GB = 2
    TEST_MNT_POINT = '/mnt/nfs'
    TEST_MNT_POINT_BASE = '/mnt'
    TEST_LOCAL_PATH = '/mnt/nfs/volume-123'
    TEST_VOLUME_PATH = '/export/volume-123'
    TEST_SNAP_PATH = '/export/snapshot-123'

    def setUp(self):
        super(IBMNASDriverTestCase, self).setUp()
        self._driver = ibmnas.IBMNAS_NFSDriver(configuration=
                                               conf.Configuration(None))
        self._mock = mock.Mock()
        self._def_flags = {'nas_ip': 'hostname',
                           'nas_login': 'user',
                           'nas_ssh_port': 22,
                           'nas_password': 'pass',
                           'nas_private_key': 'nas.key',
                           'ibmnas_platform_type': 'v7ku',
                           'nfs_shares_config': None,
                           'nfs_sparsed_volumes': True,
                           'nfs_used_ratio': 0.95,
                           'nfs_oversub_ratio': 1.0,
                           'nfs_mount_point_base':
                           self.TEST_MNT_POINT_BASE,
                           'nfs_mount_options': None}

        self.context = context.get_admin_context()
        self.context.user_id = 'fake'
        self.context.project_id = 'fake'

    def _set_flag(self, flag, value):
        group = self._driver.configuration.config_group
        self._driver.configuration.set_override(flag, value, group)

    def _reset_flags(self):
        self._driver.configuration.local_conf.reset()
        for k, v in self._def_flags.iteritems():
            self._set_flag(k, v)

    def test_check_for_setup_error(self):
        """Check setup with bad parameters."""

        drv = self._driver

        required_flags = [
            'nas_ip',
            'nas_login',
            'nas_ssh_port']

        for flag in required_flags:
            self._set_flag(flag, None)
            self.assertRaises(exception.CinderException,
                              drv.check_for_setup_error)

        self._set_flag('nas_password', None)
        self._set_flag('nas_private_key', None)
        self.assertRaises(exception.InvalidInput,
                          self._driver.check_for_setup_error)
        self._set_flag('ibmnas_platform_type', None)
        self.assertRaises(exception.InvalidInput,
                          self._driver.check_for_setup_error)

        self._reset_flags()

    def test_get_provider_location(self):
        """Check provider location for given volume id."""

        mock = self._mock

        volume = FakeEnv()
        volume['id'] = '123'

        mock.drv._get_provider_location.return_value = self.TEST_NFS_EXPORT
        self.assertEqual(self.TEST_NFS_EXPORT,
                         mock.drv._get_provider_location(volume['id']))

    def test_get_export_path(self):
        """Check export path for the given volume."""

        mock = self._mock

        volume = FakeEnv()
        volume['id'] = '123'

        mock.drv._get_export_path.return_value = self.TEST_NFS_EXPORT.\
            split(':')[1]
        self.assertEqual(self.TEST_NFS_EXPORT.split(':')[1],
                         mock.drv._get_export_path(volume['id']))

    @mock.patch('cinder.volume.drivers.ibm.ibmnas.IBMNAS_NFSDriver.'
                '_ensure_shares_mounted')
    def test_update_volume_stats(self, mock_ensure):
        """Check update volume stats."""

        drv = self._driver
        mock_ensure.return_value = True
        fake_avail = 80 * units.Gi
        fake_size = 2 * fake_avail
        fake_used = 10 * units.Gi

        with mock.patch('cinder.volume.drivers.ibm.ibmnas.IBMNAS_NFSDriver.'
                        '_get_capacity_info',
                        return_value=(fake_avail, fake_size, fake_used)):
            stats = drv.get_volume_stats()
            self.assertEqual(stats['volume_backend_name'], 'IBMNAS_NFS')
            self.assertEqual(stats['storage_protocol'], 'nfs')
            self.assertEqual(stats['driver_version'], '1.1.0')
            self.assertEqual(stats['vendor_name'], 'IBM')

    @mock.patch('cinder.volume.drivers.ibm.ibmnas.IBMNAS_NFSDriver._run_ssh')
    def test_ssh_operation(self, mock_ssh):

        drv = self._driver
        mock_ssh.return_value = None

        self.assertEqual(None, drv._ssh_operation('ssh_cmd'))

    @mock.patch('cinder.volume.drivers.ibm.ibmnas.IBMNAS_NFSDriver._run_ssh')
    def test_ssh_operation_exception(self, mock_ssh):

        drv = self._driver
        mock_ssh.side_effect = (
            exception.VolumeBackendAPIException(data='Failed'))

        self.assertRaises(exception.VolumeBackendAPIException,
                          drv._ssh_operation, 'ssh_cmd')

    @mock.patch('cinder.volume.drivers.ibm.ibmnas.IBMNAS_NFSDriver.'
                '_ssh_operation')
    @mock.patch('oslo_concurrency.processutils.execute')
    def test_create_ibmnas_snap_mount_point_provided(self, mock_ssh,
                                                     mock_execute):
        """Create ibmnas snap if mount point is provided."""

        drv = self._driver
        mock_ssh.return_value = True
        mock_execute.return_value = True

        self.assertEqual(None, drv._create_ibmnas_snap(self.TEST_VOLUME_PATH,
                                                       self.TEST_SNAP_PATH,
                                                       self.TEST_MNT_POINT))

    @mock.patch('cinder.volume.drivers.ibm.ibmnas.IBMNAS_NFSDriver.'
                '_ssh_operation')
    @mock.patch('oslo_concurrency.processutils.execute')
    def test_create_ibmnas_snap_nas_gpfs(self, mock_execute, mock_ssh):
        """Create ibmnas snap if mount point is provided."""

        drv = self._driver
        drv.configuration.platform = 'gpfs-nas'
        mock_ssh.return_value = True
        mock_execute.return_value = True

        self.assertEqual(None, drv._create_ibmnas_snap(self.TEST_VOLUME_PATH,
                                                       self.TEST_SNAP_PATH,
                                                       self.TEST_MNT_POINT))

    @mock.patch('cinder.volume.drivers.ibm.ibmnas.IBMNAS_NFSDriver.'
                '_ssh_operation')
    def test_create_ibmnas_snap_no_mount_point_provided(self, mock_ssh):
        """Create ibmnas snap if no mount point is provided."""

        drv = self._driver
        mock_ssh.return_value = True

        self.assertEqual(None, drv._create_ibmnas_snap(self.TEST_VOLUME_PATH,
                                                       self.TEST_SNAP_PATH,
                                                       None))

    @mock.patch('cinder.volume.drivers.ibm.ibmnas.IBMNAS_NFSDriver.'
                '_ssh_operation')
    def test_create_ibmnas_snap_nas_gpfs_no_mount(self, mock_ssh):
        """Create ibmnas snap (gpfs-nas) if mount point is provided."""

        drv = self._driver
        drv.configuration.platform = 'gpfs-nas'
        mock_ssh.return_value = True

        drv._create_ibmnas_snap(self.TEST_VOLUME_PATH,
                                self.TEST_SNAP_PATH, None)

    @mock.patch('cinder.volume.drivers.ibm.ibmnas.IBMNAS_NFSDriver.'
                '_ssh_operation')
    def test_create_ibmnas_copy(self, mock_ssh):
        """Create ibmnas copy test case."""

        drv = self._driver
        TEST_DEST_SNAP = '/export/snapshot-123.snap'
        TEST_DEST_PATH = '/export/snapshot-123'
        mock_ssh.return_value = True

        drv._create_ibmnas_copy(self.TEST_VOLUME_PATH,
                                TEST_DEST_PATH,
                                TEST_DEST_SNAP)

    @mock.patch('cinder.volume.drivers.ibm.ibmnas.IBMNAS_NFSDriver.'
                '_ssh_operation')
    def test_create_ibmnas_copy_nas_gpfs(self, mock_ssh):
        """Create ibmnas copy for gpfs-nas platform test case."""

        drv = self._driver
        TEST_DEST_SNAP = '/export/snapshot-123.snap'
        TEST_DEST_PATH = '/export/snapshot-123'
        drv.configuration.platform = 'gpfs-nas'
        mock_ssh.return_value = True

        drv._create_ibmnas_copy(self.TEST_VOLUME_PATH,
                                TEST_DEST_PATH,
                                TEST_DEST_SNAP)

    @mock.patch('cinder.image.image_utils.resize_image')
    def test_resize_volume_file(self, mock_size):
        """Resize volume file test case."""

        drv = self._driver
        mock_size.return_value = True

        self.assertTrue(drv._resize_volume_file(self.TEST_LOCAL_PATH,
                                                self.TEST_EXTEND_SIZE_IN_GB))

    @mock.patch('cinder.image.image_utils.resize_image')
    def test_resize_volume_exception(self, mock_size):
        """Resize volume file test case."""

        drv = self._driver
        mock_size.side_effect = (
            exception.VolumeBackendAPIException(data='Failed'))

        self.assertRaises(exception.VolumeBackendAPIException,
                          drv._resize_volume_file,
                          self.TEST_LOCAL_PATH,
                          self.TEST_EXTEND_SIZE_IN_GB)

    @mock.patch('cinder.volume.drivers.ibm.ibmnas.IBMNAS_NFSDriver.local_path')
    @mock.patch('cinder.volume.drivers.ibm.ibmnas.IBMNAS_NFSDriver.'
                '_resize_volume_file')
    def test_extend_volume(self, mock_resize, mock_local):
        """Extend volume to greater size test case."""

        drv = self._driver
        mock_local.return_value = self.TEST_LOCAL_PATH
        mock_resize.return_value = True
        volume = FakeEnv()
        volume['name'] = 'vol-123'

        drv.extend_volume(volume,
                          self.TEST_EXTEND_SIZE_IN_GB)

    @mock.patch('cinder.volume.drivers.ibm.ibmnas.IBMNAS_NFSDriver._run_ssh')
    @mock.patch('oslo_concurrency.processutils.execute')
    def test_delete_snapfiles(self, mock_execute, mock_ssh):
        """Delete_snapfiles test case."""

        drv = self._driver
        expected = ('Parent Depth Parent inode'
                    'File name\n yes    0 /ibm/gpfs0/gshare/\n'
                    'volume-123\n EFSSG1000I The command'
                    'completed successfully.', '')
        mock_ssh.return_value = expected
        mock_execute.return_value = expected

        drv._delete_snapfiles(self.TEST_VOLUME_PATH,
                              self.TEST_MNT_POINT)

    @mock.patch('cinder.volume.drivers.ibm.ibmnas.IBMNAS_NFSDriver._run_ssh')
    @mock.patch('oslo_concurrency.processutils.execute')
    def test_delete_snapfiles_nas_gpfs(self, mock_execute, mock_ssh):
        """Delete_snapfiles for gpfs-nas platform test case."""

        drv = self._driver
        drv.configuration.platform = 'gpfs-nas'
        expected = ('Parent  Depth   Parent inode'
                    'File name\n'
                    '------  -----  -------------'
                    '-  ---------\n'
                    'yes      0\n'
                    '/ibm/gpfs0/gshare/volume-123', '')
        mock_ssh.return_value = expected
        mock_execute.return_value = expected

        drv._delete_snapfiles(self.TEST_VOLUME_PATH,
                              self.TEST_MNT_POINT)

    def test_delete_volume_no_provider_location(self):
        """Delete volume with no provider location specified."""

        drv = self._driver

        volume = FakeEnv()
        volume['name'] = 'volume-123'
        volume['provider_location'] = None

        result = drv.delete_volume(volume)
        self.assertIsNone(result)

    @mock.patch('cinder.volume.drivers.ibm.ibmnas.IBMNAS_NFSDriver.'
                '_get_export_path')
    @mock.patch('cinder.volume.drivers.ibm.ibmnas.IBMNAS_NFSDriver.'
                '_delete_snapfiles')
    def test_delete_volume(self, mock_snap, mock_export):
        """Delete volume test case."""

        drv = self._driver
        mock_export.return_value = self.TEST_VOLUME_PATH
        mock_snap.return_value = True

        volume = FakeEnv()
        volume['id'] = '123'
        volume['name'] = '/volume-123'
        volume['provider_location'] = self.TEST_VOLUME_PATH

        self.assertEqual(None, drv.delete_volume(volume))

    @mock.patch('cinder.volume.drivers.ibm.ibmnas.IBMNAS_NFSDriver.'
                '_get_export_path')
    @mock.patch('cinder.volume.drivers.ibm.ibmnas.IBMNAS_NFSDriver.'
                '_get_provider_location')
    @mock.patch('cinder.volume.drivers.ibm.ibmnas.IBMNAS_NFSDriver.'
                '_get_mount_point_for_share')
    @mock.patch('cinder.volume.drivers.ibm.ibmnas.IBMNAS_NFSDriver.'
                '_create_ibmnas_snap')
    def test_create_snapshot(self, mock_snap, mock_mount, mock_provider,
                             mock_export):
        """Create snapshot simple test case."""

        drv = self._driver
        mock_export.return_value = self.TEST_LOCAL_PATH
        mock_provider.return_value = self.TEST_VOLUME_PATH
        mock_mount.return_value = self.TEST_MNT_POINT
        mock_snap.return_value = True

        volume = FakeEnv()
        volume['id'] = '123'
        volume['name'] = 'volume-123'

        snapshot = FakeEnv()
        snapshot['volume_id'] = volume['id']
        snapshot['volume_name'] = '/volume-123'
        snapshot['name'] = '/snapshot-123'

        drv.create_snapshot(snapshot)

    @mock.patch('cinder.volume.drivers.ibm.ibmnas.IBMNAS_NFSDriver.'
                '_get_provider_location')
    @mock.patch('cinder.volume.drivers.ibm.ibmnas.IBMNAS_NFSDriver.'
                '_get_mount_point_for_share')
    @mock.patch('oslo_concurrency.processutils.execute')
    def test_delete_snapshot(self, mock_execute, mock_mount, mock_provider):
        """Delete snapshot simple test case."""

        drv = self._driver
        mock_provider.return_value = self.TEST_VOLUME_PATH
        mock_mount.return_value = self.TEST_LOCAL_PATH
        mock_execute.return_value = True

        volume = FakeEnv()
        volume['id'] = '123'
        volume['provider_location'] = self.TEST_NFS_EXPORT

        snapshot = FakeEnv()
        snapshot['volume_id'] = volume['id']
        snapshot['volume_name'] = 'volume-123'
        snapshot['name'] = 'snapshot-123'

        drv.delete_snapshot(snapshot)

    @mock.patch('cinder.volume.drivers.ibm.ibmnas.IBMNAS_NFSDriver.'
                '_get_export_path')
    @mock.patch('cinder.volume.drivers.ibm.ibmnas.IBMNAS_NFSDriver.'
                '_create_ibmnas_copy')
    @mock.patch('cinder.volume.drivers.ibm.ibmnas.IBMNAS_NFSDriver.'
                '_find_share')
    @mock.patch('cinder.volume.drivers.ibm.ibmnas.IBMNAS_NFSDriver.local_path')
    @mock.patch('cinder.volume.drivers.ibm.ibmnas.IBMNAS_NFSDriver.'
                '_set_rw_permissions_for_owner')
    @mock.patch('cinder.volume.drivers.ibm.ibmnas.IBMNAS_NFSDriver.'
                '_resize_volume_file')
    def test_create_cloned_volume(self, mock_resize, mock_rw, mock_local,
                                  mock_find, mock_copy, mock_export):
        """Clone volume with equal size test case."""

        drv = self._driver
        mock_export.return_value = self.TEST_VOLUME_PATH
        mock_copy.return_value = True
        mock_find.return_value = self.TEST_LOCAL_PATH
        mock_local.return_value = self.TEST_LOCAL_PATH
        mock_rw.return_value = True
        mock_resize.return_value = True

        volume_src = FakeEnv()
        volume_src['id'] = '123'
        volume_src['name'] = '/volume-123'
        volume_src.size = self.TEST_SIZE_IN_GB

        volume_dest = FakeEnv()
        volume_dest['id'] = '456'
        volume_dest['name'] = '/volume-456'
        volume_dest['size'] = self.TEST_SIZE_IN_GB
        volume_dest.size = self.TEST_SIZE_IN_GB

        self.assertEqual({'provider_location': self.TEST_LOCAL_PATH},
                         drv.create_cloned_volume(volume_dest, volume_src))

    @mock.patch('cinder.volume.drivers.ibm.ibmnas.IBMNAS_NFSDriver.'
                '_get_export_path')
    @mock.patch('cinder.volume.drivers.ibm.ibmnas.IBMNAS_NFSDriver.'
                '_create_ibmnas_snap')
    @mock.patch('cinder.volume.drivers.ibm.ibmnas.IBMNAS_NFSDriver.'
                '_find_share')
    @mock.patch('cinder.volume.drivers.ibm.ibmnas.IBMNAS_NFSDriver.local_path')
    @mock.patch('cinder.volume.drivers.ibm.ibmnas.IBMNAS_NFSDriver.'
                '_set_rw_permissions_for_owner')
    @mock.patch('cinder.volume.drivers.ibm.ibmnas.IBMNAS_NFSDriver.'
                '_resize_volume_file')
    def test_create_volume_from_snapshot(self, mock_resize, mock_rw,
                                         mock_local, mock_find, mock_snap,
                                         mock_export):
        """Create volume from snapshot test case."""

        drv = self._driver
        mock_export.return_value = '/export'
        mock_snap.return_value = self.TEST_LOCAL_PATH
        mock_find.return_value = self.TEST_LOCAL_PATH
        mock_local.return_value = self.TEST_VOLUME_PATH
        mock_rw.return_value = True
        mock_resize.return_value = True

        volume = FakeEnv()
        volume['id'] = '123'
        volume['name'] = '/volume-123'
        volume['size'] = self.TEST_SIZE_IN_GB

        snapshot = FakeEnv()
        snapshot['volume_id'] = volume['id']
        snapshot['volume_name'] = 'volume-123'
        snapshot['volume_size'] = self.TEST_SIZE_IN_GB
        snapshot.name = '/snapshot-123'

        self.assertEqual({'provider_location': self.TEST_LOCAL_PATH},
                         drv.create_volume_from_snapshot(volume, snapshot))
