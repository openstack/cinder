
# Copyright IBM Corp. 2013 All Rights Reserved
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

import os
import tempfile
from unittest import mock

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_utils import timeutils
from oslo_utils import units

from cinder import context
from cinder import exception
from cinder import objects
from cinder.objects import fields
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import test
from cinder.tests.unit import utils as test_utils
from cinder import utils
from cinder.volume import configuration as conf
from cinder.volume.drivers.ibm import gpfs
from cinder.volume import volume_types


CONF = cfg.CONF


class FakeQemuImgInfo(object):
    def __init__(self):
        self.file_format = None
        self.backing_file = None


class GPFSDriverTestCase(test.TestCase):
    driver_name = "cinder.volume.drivers.gpfs.GPFSDriver"
    context = context.get_admin_context()

    def _execute_wrapper(self, cmd, *args, **kwargs):
        try:
            kwargs.pop('run_as_root')
        except KeyError:
            pass

        return utils.execute(cmd, *args, **kwargs)

    def setUp(self):
        super(GPFSDriverTestCase, self).setUp()
        self.volumes_path = tempfile.mkdtemp(prefix="gpfs_")
        self.images_dir = '%s/images' % self.volumes_path
        self.addCleanup(self._cleanup, self.images_dir, self.volumes_path)

        if not os.path.exists(self.volumes_path):
            os.mkdir(self.volumes_path)
        if not os.path.exists(self.images_dir):
            os.mkdir(self.images_dir)
        self.image_id = '70a599e0-31e7-49b7-b260-868f441e862b'

        self.driver = gpfs.GPFSDriver(
            configuration=conf.Configuration([], conf.SHARED_CONF_GROUP))
        self.driver.gpfs_execute = self._execute_wrapper
        exec_patcher = mock.patch.object(self.driver, '_execute',
                                         self._execute_wrapper)
        exec_patcher.start()
        self.addCleanup(exec_patcher.stop)
        self.driver._cluster_id = '123456'
        self.driver._gpfs_device = '/dev/gpfs'
        self.driver._storage_pool = 'system'
        self.driver._encryption_state = 'yes'

        self.override_config('volume_driver', self.driver_name,
                             conf.SHARED_CONF_GROUP)
        self.override_config('gpfs_mount_point_base', self.volumes_path,
                             conf.SHARED_CONF_GROUP)

        self.context = context.get_admin_context()
        self.context.user_id = 'fake'
        self.context.project_id = 'fake'
        self.updated_at = timeutils.utcnow()
        CONF.gpfs_images_dir = self.images_dir

    def _cleanup(self, images_dir, volumes_path):
        try:
            os.rmdir(images_dir)
            os.rmdir(volumes_path)
        except OSError:
            pass

    def test_different(self):
        self.assertTrue(gpfs._different((True, False)))
        self.assertFalse(gpfs._different((True, True)))
        self.assertFalse(gpfs._different(None))

    def test_sizestr(self):
        self.assertEqual('10G', gpfs._sizestr('10'))

    @mock.patch('cinder.utils.execute')
    def test_gpfs_local_execute(self, mock_exec):
        mock_exec.return_value = 'test'
        self.driver._gpfs_local_execute('test')
        expected = [mock.call('test', run_as_root=True)]
        self.assertEqual(expected, mock_exec.mock_calls)

    @mock.patch('cinder.utils.execute')
    def test_get_gpfs_state_ok(self, mock_exec):
        mock_exec.return_value = ('mmgetstate::HEADER:version:reserved:'
                                  'reserved:nodeName:nodeNumber:state:quorum:'
                                  'nodesUp:totalNodes:remarks:cnfsState:\n'
                                  'mmgetstate::0:1:::devstack:3:active:2:3:3:'
                                  'quorum node:(undefined):', '')
        self.assertTrue(self.driver._get_gpfs_state().splitlines()[1].
                        startswith('mmgetstate::0:1:::devstack'))

    @mock.patch('cinder.utils.execute')
    def test_get_gpfs_state_fail_mmgetstate(self, mock_exec):
        mock_exec.side_effect = processutils.ProcessExecutionError(
            stdout='test', stderr='test')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._get_gpfs_state)

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._get_gpfs_state')
    def test_check_gpfs_state_ok(self, mock_get_gpfs_state):
        mock_get_gpfs_state.return_value = ('mmgetstate::HEADER:version:'
                                            'reserved:reserved:nodeName:'
                                            'nodeNumber:state:quorum:nodesUp:'
                                            'totalNodes:remarks:cnfsState:\n'
                                            'mmgetstate::0:1:::devstack:3:'
                                            'active:2:3:3:'
                                            'quorum node:(undefined):')
        self.driver._check_gpfs_state()

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._get_gpfs_state')
    def test_check_gpfs_state_fail_not_active(self, mock_get_gpfs_state):
        mock_get_gpfs_state.return_value = ('mmgetstate::HEADER:version:'
                                            'reserved:reserved:nodeName:'
                                            'nodeNumber:state:quorum:nodesUp:'
                                            'totalNodes:remarks:cnfsState:\n'
                                            'mmgetstate::0:1:::devstack:3:'
                                            'arbitrating:2:3:3:'
                                            'quorum node:(undefined):')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._check_gpfs_state)

    @mock.patch('cinder.utils.execute')
    def test_get_fs_from_path_ok(self, mock_exec):
        mock_exec.return_value = ('Filesystem           1K-blocks      '
                                  'Used Available Use%% Mounted on\n'
                                  '%s             10485760    531968   9953792'
                                  '   6%% /gpfs0' % self.driver._gpfs_device,
                                  '')
        self.assertEqual(self.driver._gpfs_device,
                         self.driver._get_filesystem_from_path('/gpfs0'))

    @mock.patch('cinder.utils.execute')
    def test_get_fs_from_path_fail_path(self, mock_exec):
        mock_exec.return_value = ('Filesystem           1K-blocks      '
                                  'Used Available Use% Mounted on\n'
                                  'test             10485760    531968   '
                                  '9953792   6% /gpfs0', '')
        self.assertNotEqual(self.driver._gpfs_device,
                            self.driver._get_filesystem_from_path('/gpfs0'))

    @mock.patch('cinder.utils.execute')
    def test_get_fs_from_path_fail_raise(self, mock_exec):
        mock_exec.side_effect = processutils.ProcessExecutionError(
            stdout='test', stderr='test')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._get_filesystem_from_path, '/gpfs0')

    @mock.patch('cinder.utils.execute')
    def test_get_gpfs_cluster_id_ok(self, mock_exec):
        mock_exec.return_value = ('mmlsconfig::HEADER:version:reserved:'
                                  'reserved:configParameter:value:nodeList:\n'
                                  'mmlsconfig::0:1:::clusterId:%s::'
                                  % self.driver._cluster_id, '')
        self.assertEqual(self.driver._cluster_id,
                         self.driver._get_gpfs_cluster_id())

    @mock.patch('cinder.utils.execute')
    def test_get_gpfs_cluster_id_fail_id(self, mock_exec):
        mock_exec.return_value = ('mmlsconfig::HEADER.:version:reserved:'
                                  'reserved:configParameter:value:nodeList:\n'
                                  'mmlsconfig::0:1:::clusterId:test::', '')
        self.assertNotEqual(self.driver._cluster_id,
                            self.driver._get_gpfs_cluster_id())

    @mock.patch('cinder.utils.execute')
    def test_get_gpfs_cluster_id_fail_raise(self, mock_exec):
        mock_exec.side_effect = processutils.ProcessExecutionError(
            stdout='test', stderr='test')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._get_gpfs_cluster_id)

    @mock.patch('cinder.utils.execute')
    def test_get_fileset_from_path_ok(self, mock_exec):
        mock_exec.return_value = ('file name:            /gpfs0\n'
                                  'metadata replication: 1 max 2\n'
                                  'data replication:     1 max 2\n'
                                  'immutable:            no\n'
                                  'appendOnly:           no\n'
                                  'flags:\n'
                                  'storage pool name:    system\n'
                                  'fileset name:         root\n'
                                  'snapshot name:\n'
                                  'Windows attributes:   DIRECTORY', '')
        self.driver._get_fileset_from_path('')

    @mock.patch('cinder.utils.execute')
    def test_get_fileset_from_path_fail_mmlsattr(self, mock_exec):
        mock_exec.side_effect = processutils.ProcessExecutionError(
            stdout='test', stderr='test')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._get_fileset_from_path, '')

    @mock.patch('cinder.utils.execute')
    def test_get_fileset_from_path_fail_find_fileset(self, mock_exec):
        mock_exec.return_value = ('file name:            /gpfs0\n'
                                  'metadata replication: 1 max 2\n'
                                  'data replication:     1 max 2\n'
                                  'immutable:            no\n'
                                  'appendOnly:           no\n'
                                  'flags:\n'
                                  'storage pool name:    system\n'
                                  '*** name:         root\n'
                                  'snapshot name:\n'
                                  'Windows attributes:   DIRECTORY', '')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._get_fileset_from_path, '')

    @mock.patch('cinder.utils.execute')
    def test_verify_gpfs_pool_ok(self, mock_exec):
        mock_exec.return_value = ('Storage pools in file system at \'/gpfs0\':'
                                  '\n'
                                  'Name                    Id   BlkSize Data '
                                  'Meta '
                                  'Total Data in (KB)   Free Data in (KB)   '
                                  'Total Meta in (KB)    Free Meta in (KB)\n'
                                  'system                   0    256 KB  yes  '
                                  'yes '
                                  '      10485760        9953792 ( 95%)       '
                                  '10485760        9954560 ( 95%)', '')
        self.assertEqual('/dev/gpfs', self.driver._gpfs_device)
        self.assertTrue(self.driver._verify_gpfs_pool('/dev/gpfs'))

    @mock.patch('cinder.utils.execute')
    def test_verify_gpfs_pool_fail_pool(self, mock_exec):
        mock_exec.return_value = ('Storage pools in file system at \'/gpfs0\':'
                                  '\n'
                                  'Name                    Id   BlkSize Data '
                                  'Meta '
                                  'Total Data in (KB)   Free Data in (KB)   '
                                  'Total Meta in (KB)    Free Meta in (KB)\n'
                                  'test                   0    256 KB  yes  '
                                  'yes'
                                  '       10485760        9953792 ( 95%)'
                                  '       10485760        9954560 ( 95%)', '')
        self.assertEqual('/dev/gpfs', self.driver._gpfs_device)
        self.assertTrue(self.driver._verify_gpfs_pool('/dev/gpfs'))

    @mock.patch('cinder.utils.execute')
    def test_verify_gpfs_pool_fail_raise(self, mock_exec):
        mock_exec.side_effect = processutils.ProcessExecutionError(
            stdout='test', stderr='test')
        self.assertFalse(self.driver._verify_gpfs_pool('/dev/gpfs'))

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._verify_gpfs_pool')
    @mock.patch('cinder.utils.execute')
    def test_update_volume_storage_pool_ok(self, mock_exec, mock_verify_pool):
        mock_verify_pool.return_value = True
        self.assertTrue(self.driver._update_volume_storage_pool('', 'system'))

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._verify_gpfs_pool')
    @mock.patch('cinder.utils.execute')
    def test_update_volume_storage_pool_ok_pool_none(self,
                                                     mock_exec,
                                                     mock_verify_pool):
        mock_verify_pool.return_value = True
        self.assertTrue(self.driver._update_volume_storage_pool('', None))

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._verify_gpfs_pool')
    @mock.patch('cinder.utils.execute')
    def test_update_volume_storage_pool_fail_pool(self,
                                                  mock_exec,
                                                  mock_verify_pool):
        mock_verify_pool.return_value = False
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._update_volume_storage_pool,
                          '',
                          'system')

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._verify_gpfs_pool')
    @mock.patch('cinder.utils.execute')
    def test_update_volume_storage_pool_fail_mmchattr(self,
                                                      mock_exec,
                                                      mock_verify_pool):
        mock_exec.side_effect = processutils.ProcessExecutionError(
            stdout='test', stderr='test')
        mock_verify_pool.return_value = True
        self.assertFalse(self.driver._update_volume_storage_pool('', 'system'))

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_get_filesystem_from_path')
    @mock.patch('cinder.utils.execute')
    def test_get_gpfs_fs_release_level_ok(self,
                                          mock_exec,
                                          mock_fs_from_path):
        mock_exec.return_value = ('mmlsfs::HEADER:version:reserved:reserved:'
                                  'deviceName:fieldName:data:remarks:\n'
                                  'mmlsfs::0:1:::gpfs:filesystemVersion:14.03 '
                                  '(4.1.0.0):\n'
                                  'mmlsfs::0:1:::gpfs:filesystemVersionLocal:'
                                  '14.03 (4.1.0.0):\n'
                                  'mmlsfs::0:1:::gpfs:filesystemVersionManager'
                                  ':14.03 (4.1.0.0):\n'
                                  'mmlsfs::0:1:::gpfs:filesystemVersion'
                                  'Original:14.03 (4.1.0.0):\n'
                                  'mmlsfs::0:1:::gpfs:filesystemHighest'
                                  'Supported:14.03 (4.1.0.0):', '')
        mock_fs_from_path.return_value = '/dev/gpfs'
        self.assertEqual(('/dev/gpfs', 1403),
                         self.driver._get_gpfs_fs_release_level(''))

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_get_filesystem_from_path')
    @mock.patch('cinder.utils.execute')
    def test_get_gpfs_fs_release_level_fail_mmlsfs(self,
                                                   mock_exec,
                                                   mock_fs_from_path):
        mock_exec.side_effect = processutils.ProcessExecutionError(
            stdout='test', stderr='test')
        mock_fs_from_path.return_value = '/dev/gpfs'
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._get_gpfs_fs_release_level, '')

    @mock.patch('cinder.utils.execute')
    def test_get_gpfs_cluster_release_level_ok(self, mock_exec):
        mock_exec.return_value = ('mmlsconfig::HEADER:version:reserved:'
                                  'reserved:configParameter:value:nodeList:\n'
                                  'mmlsconfig::0:1:::minReleaseLevel:1403::',
                                  '')
        self.assertEqual(1403, self.driver._get_gpfs_cluster_release_level())

    @mock.patch('cinder.utils.execute')
    def test_get_gpfs_cluster_release_level_fail_mmlsconfig(self, mock_exec):
        mock_exec.side_effect = processutils.ProcessExecutionError(
            stdout='test', stderr='test')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._get_gpfs_cluster_release_level)

    @mock.patch('cinder.utils.execute')
    def test_is_gpfs_path_fail_mmlsattr(self, mock_exec):
        mock_exec.side_effect = processutils.ProcessExecutionError(
            stdout='test', stderr='test')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._is_gpfs_path, '/dummy/path')

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_get_fileset_from_path')
    @mock.patch('cinder.utils.execute')
    def test_is_same_fileset_ok(self,
                                mock_exec,
                                mock_get_fileset_from_path):
        mock_get_fileset_from_path.return_value = True
        self.assertTrue(self.driver._is_same_fileset('', ''))
        mock_get_fileset_from_path.side_effect = [True, False]
        self.assertFalse(self.driver._is_same_fileset('', ''))

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_get_available_capacity')
    @mock.patch('cinder.utils.execute')
    def test_same_cluster_ok(self, mock_exec, mock_avail_capacity):
        mock_avail_capacity.return_value = (10192683008, 10737418240)
        stats = self.driver.get_volume_stats()
        loc = stats['location_info']
        cap = {'location_info': loc}
        host = {'host': 'foo', 'capabilities': cap}
        self.assertTrue(self.driver._same_cluster(host))

        locinfo = stats['location_info'] + '_'
        loc = locinfo
        cap = {'location_info': loc}
        host = {'host': 'foo', 'capabilities': cap}
        self.assertFalse(self.driver._same_cluster(host))

    @mock.patch('cinder.utils.execute')
    def test_set_rw_permission(self, mock_exec):
        self.driver._set_rw_permission('')

    @mock.patch('cinder.utils.execute')
    def test_can_migrate_locally(self, mock_exec):
        host = {'host': 'foo', 'capabilities': ''}
        self.assertIsNone(self.driver._can_migrate_locally(host))

        loc = 'GPFSDriver:%s' % self.driver._cluster_id
        cap = {'location_info': loc}
        host = {'host': 'foo', 'capabilities': cap}
        self.assertIsNone(self.driver._can_migrate_locally(host))

        loc = 'GPFSDriver_:%s:testpath' % self.driver._cluster_id
        cap = {'location_info': loc}
        host = {'host': 'foo', 'capabilities': cap}
        self.assertIsNone(self.driver._can_migrate_locally(host))

        loc = 'GPFSDriver:%s:testpath' % (self.driver._cluster_id + '_')
        cap = {'location_info': loc}
        host = {'host': 'foo', 'capabilities': cap}
        self.assertIsNone(self.driver._can_migrate_locally(host))

        loc = 'GPFSDriver:%s:testpath' % self.driver._cluster_id
        cap = {'location_info': loc}
        host = {'host': 'foo', 'capabilities': cap}
        self.assertEqual('testpath', self.driver._can_migrate_locally(host))

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_get_gpfs_encryption_status')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_get_gpfs_cluster_release_level')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._verify_gpfs_pool')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_get_filesystem_from_path')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_get_gpfs_cluster_id')
    @mock.patch('cinder.utils.execute')
    def test_do_setup_ok(self,
                         mock_exec,
                         mock_get_gpfs_cluster_id,
                         mock_get_filesystem_from_path,
                         mock_verify_gpfs_pool,
                         mock_get_gpfs_fs_rel_lev,
                         mock_verify_encryption_state):
        ctxt = self.context
        mock_get_gpfs_cluster_id.return_value = self.driver._cluster_id
        mock_get_filesystem_from_path.return_value = '/dev/gpfs'
        mock_verify_gpfs_pool.return_value = True
        mock_get_gpfs_fs_rel_lev.return_value = 1405
        mock_verify_encryption_state.return_value = 'Yes'
        self.driver.do_setup(ctxt)

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_get_gpfs_cluster_release_level')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._verify_gpfs_pool')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_get_filesystem_from_path')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_get_gpfs_cluster_id')
    @mock.patch('cinder.utils.execute')
    def test_do_setup_no_encryption(self,
                                    mock_exec,
                                    mock_get_gpfs_cluster_id,
                                    mock_get_filesystem_from_path,
                                    mock_verify_gpfs_pool,
                                    mock_get_gpfs_fs_rel_lev):
        ctxt = self.context
        mock_get_gpfs_cluster_id.return_value = self.driver._cluster_id
        mock_get_filesystem_from_path.return_value = '/dev/gpfs'
        mock_verify_gpfs_pool.return_value = True
        mock_get_gpfs_fs_rel_lev.return_value = 1403
        self.driver.do_setup(ctxt)

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._verify_gpfs_pool')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_get_filesystem_from_path')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_get_gpfs_cluster_id')
    @mock.patch('cinder.utils.execute')
    def test_do_setup_fail_get_cluster_id(self,
                                          mock_exec,
                                          mock_get_gpfs_cluster_id,
                                          mock_get_filesystem_from_path,
                                          mock_verify_gpfs_pool):
        ctxt = self.context
        mock_get_gpfs_cluster_id.side_effect = (
            processutils.ProcessExecutionError(stdout='test', stderr='test'))
        mock_get_filesystem_from_path.return_value = '/dev/gpfs'
        mock_verify_gpfs_pool.return_value = True
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.do_setup, ctxt)

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._verify_gpfs_pool')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_get_filesystem_from_path')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_get_gpfs_cluster_id')
    @mock.patch('cinder.utils.execute')
    def test_do_setup_fail_get_fs_from_path(self,
                                            mock_exec,
                                            mock_get_gpfs_cluster_id,
                                            mock_get_fs_from_path,
                                            mock_verify_gpfs_pool):
        ctxt = self.context
        mock_get_gpfs_cluster_id.return_value = self.driver._cluster_id
        mock_get_fs_from_path.side_effect = (
            processutils.ProcessExecutionError(stdout='test', stderr='test'))
        mock_verify_gpfs_pool.return_value = True
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.do_setup, ctxt)

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._verify_gpfs_pool')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_get_filesystem_from_path')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_get_gpfs_cluster_id')
    @mock.patch('cinder.utils.execute')
    def test_do_setup_fail_volume(self,
                                  mock_exec,
                                  mock_get_gpfs_cluster_id,
                                  mock_get_filesystem_from_path,
                                  mock_verify_gpfs_pool):
        ctxt = self.context
        mock_get_gpfs_cluster_id. return_value = self.driver._cluster_id
        mock_get_filesystem_from_path.return_value = '/dev/gpfs'
        mock_verify_gpfs_pool.return_value = False
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.do_setup, ctxt)

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._check_gpfs_state')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._is_gpfs_path')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_get_gpfs_fs_release_level')
    def test_check_for_setup_error_fail_conf(self,
                                             mock_get_gpfs_fs_rel_lev,
                                             mock_is_gpfs_path,
                                             mock_check_gpfs_state):
        fake_fs = '/dev/gpfs'
        fake_fs_release = 1400
        fake_cluster_release = 1201

        # fail configuration.gpfs_mount_point_base is None
        org_value = self.driver.configuration.gpfs_mount_point_base
        self.override_config('gpfs_mount_point_base', None,
                             conf.SHARED_CONF_GROUP)
        mock_get_gpfs_fs_rel_lev.return_value = (fake_fs, fake_fs_release)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.check_for_setup_error)
        self.override_config('gpfs_mount_point_base', org_value,
                             conf.SHARED_CONF_GROUP)

        # fail configuration.gpfs_images_share_mode and
        # configuration.gpfs_images_dir is None
        self.override_config('gpfs_images_share_mode', 'copy',
                             conf.SHARED_CONF_GROUP)
        self.override_config('gpfs_images_dir', None, conf.SHARED_CONF_GROUP)
        org_value_dir = self.driver.configuration.gpfs_images_dir
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.check_for_setup_error)
        self.override_config('gpfs_images_dir', org_value_dir,
                             conf.SHARED_CONF_GROUP)

        # fail configuration.gpfs_images_share_mode == 'copy_on_write' and not
        # _same_filesystem(configuration.gpfs_mount_point_base,
        # configuration.gpfs_images_dir)
        self.override_config('gpfs_images_share_mode', 'copy_on_write',
                             conf.SHARED_CONF_GROUP)
        with mock.patch('cinder.volume.drivers.ibm.gpfs._same_filesystem',
                        return_value=False):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.driver.check_for_setup_error)

        # fail self.configuration.gpfs_images_share_mode == 'copy_on_write' and
        # not self._is_same_fileset(self.configuration.gpfs_mount_point_base,
        # self.configuration.gpfs_images_dir)
        with mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                        '_is_same_fileset', return_value=False):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.driver.check_for_setup_error)

        # fail directory is None
        self.override_config('gpfs_images_share_mode', None,
                             conf.SHARED_CONF_GROUP)
        org_value_dir = self.driver.configuration.gpfs_images_dir
        self.override_config('gpfs_images_dir', None, conf.SHARED_CONF_GROUP)
        with mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                        '_get_gpfs_cluster_release_level',
                        return_value=fake_cluster_release):
            self.driver.check_for_setup_error()
        self.override_config('gpfs_images_dir', org_value_dir,
                             conf.SHARED_CONF_GROUP)

        # fail directory.startswith('/')
        org_value_mount = self.driver.configuration.gpfs_mount_point_base
        self.override_config('gpfs_mount_point_base', '_' + self.volumes_path,
                             conf.SHARED_CONF_GROUP)
        self.override_config('gpfs_images_share_mode', None,
                             conf.SHARED_CONF_GROUP)
        with mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                        '_get_gpfs_cluster_release_level',
                        return_value=fake_cluster_release):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.driver.check_for_setup_error)
        self.override_config('gpfs_mount_point_base', org_value_mount,
                             conf.SHARED_CONF_GROUP)

        # fail os.path.isdir(directory)
        org_value_mount = self.driver.configuration.gpfs_mount_point_base
        self.override_config('gpfs_mount_point_base', self.volumes_path + '_',
                             conf.SHARED_CONF_GROUP)
        org_value_dir = self.driver.configuration.gpfs_images_dir
        self.override_config('gpfs_images_dir', None, conf.SHARED_CONF_GROUP)
        with mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                        '_get_gpfs_cluster_release_level',
                        return_value=fake_cluster_release):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.driver.check_for_setup_error)
        self.override_config('gpfs_mount_point_base', org_value_mount,
                             conf.SHARED_CONF_GROUP)
        self.override_config('gpfs_images_dir', org_value_dir,
                             conf.SHARED_CONF_GROUP)

        # fail not cluster release level >= GPFS_CLONE_MIN_RELEASE
        org_fake_cluster_release = fake_cluster_release
        fake_cluster_release = 1105
        self.override_config('gpfs_mount_point_base', self.volumes_path,
                             conf.SHARED_CONF_GROUP)
        self.override_config('gpfs_images_dir', None, conf.SHARED_CONF_GROUP)
        with mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                        '_get_gpfs_cluster_release_level',
                        return_value=fake_cluster_release):
            with mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                            '_get_gpfs_fs_release_level',
                            return_value=(fake_fs, fake_fs_release)):
                self.assertRaises(exception.VolumeBackendAPIException,
                                  self.driver.check_for_setup_error)
        fake_cluster_release = org_fake_cluster_release

        # fail not fs release level >= GPFS_CLONE_MIN_RELEASE
        org_fake_fs_release = fake_fs_release
        fake_fs_release = 1105
        self.override_config('gpfs_mount_point_base', self.volumes_path,
                             conf.SHARED_CONF_GROUP)
        self.override_config('gpfs_images_dir', None, conf.SHARED_CONF_GROUP)
        with mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                        '_get_gpfs_cluster_release_level',
                        return_value=fake_cluster_release):
            with mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                            '_get_gpfs_fs_release_level',
                            return_value=(fake_fs, fake_fs_release)):
                self.assertRaises(exception.VolumeBackendAPIException,
                                  self.driver.check_for_setup_error)
        fake_fs_release = org_fake_fs_release

    @mock.patch('cinder.utils.execute')
    def test_create_sparse_file(self, mock_exec):
        self.driver._create_sparse_file('', 100)

    @mock.patch('cinder.utils.execute')
    def test_allocate_file_blocks(self, mock_exec):
        self.driver._allocate_file_blocks(os.path.join(self.images_dir,
                                                       'test'), 1)

    @mock.patch('cinder.utils.execute')
    def test_gpfs_change_attributes(self, mock_exec):
        options = []
        options.extend(['-T', 'test'])
        self.driver._gpfs_change_attributes(options, self.images_dir)

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._mkfs')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_gpfs_change_attributes')
    def test_set_volume_attributes(self, mock_change_attributes, mock_mkfs):
        metadata = {'data_pool_name': 'test',
                    'replicas': 'test',
                    'dio': 'test',
                    'write_affinity_depth': 'test',
                    'block_group_factor': 'test',
                    'write_affinity_failure_group': 'test',
                    'fstype': 'test',
                    'fslabel': 'test',
                    'test': 'test'}

        self.driver._set_volume_attributes('', '', metadata)

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_gpfs_change_attributes')
    def test_set_volume_attributes_no_attributes(self, mock_change_attributes):
        metadata = {}
        org_value = self.driver.configuration.gpfs_storage_pool
        self.override_config('gpfs_storage_pool', 'system',
                             conf.SHARED_CONF_GROUP)
        self.driver._set_volume_attributes('', '', metadata)
        self.override_config('gpfs_storage_pool', org_value,
                             conf.SHARED_CONF_GROUP)

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_gpfs_change_attributes')
    def test_set_volume_attributes_no_options(self, mock_change_attributes):
        metadata = {}
        org_value = self.driver.configuration.gpfs_storage_pool
        self.override_config('gpfs_storage_pool', '', conf.SHARED_CONF_GROUP)
        self.driver._set_volume_attributes('', '', metadata)
        self.override_config('gpfs_storage_pool', org_value,
                             conf.SHARED_CONF_GROUP)

    @mock.patch('cinder.utils.execute')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_allocate_file_blocks')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_set_volume_attributes')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_set_rw_permission')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_create_sparse_file')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.local_path')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_verify_gpfs_path_state')
    def test_create_volume(self,
                           mock_gpfs_path_state,
                           mock_local_path,
                           mock_sparse_file,
                           mock_rw_permission,
                           mock_set_volume_attributes,
                           mock_allocate_file_blocks,
                           mock_exec):
        mock_local_path.return_value = 'test'
        volume = self._fake_volume()
        value = {}
        value['value'] = 'test'

        org_value = self.driver.configuration.gpfs_sparse_volumes
        self.override_config('gpfs_sparse_volumes', False,
                             conf.SHARED_CONF_GROUP)
        self.driver.create_volume(volume)
        self.override_config('gpfs_sparse_volumes', org_value,
                             conf.SHARED_CONF_GROUP)

    @mock.patch('cinder.utils.execute')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_allocate_file_blocks')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_set_volume_attributes')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_set_rw_permission')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_create_sparse_file')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.local_path')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_verify_gpfs_path_state')
    def test_create_volume_no_sparse_volume(self,
                                            mock_gpfs_path_state,
                                            mock_local_path,
                                            mock_sparse_file,
                                            mock_rw_permission,
                                            mock_set_volume_attributes,
                                            mock_allocate_file_blocks,
                                            mock_exec):
        mock_local_path.return_value = 'test'
        volume = self._fake_volume()
        value = {}
        value['value'] = 'test'

        org_value = self.driver.configuration.gpfs_sparse_volumes
        self.override_config('gpfs_sparse_volumes', True,
                             conf.SHARED_CONF_GROUP)
        self.driver.create_volume(volume)
        self.override_config('gpfs_sparse_volumes', org_value,
                             conf.SHARED_CONF_GROUP)

    @mock.patch('cinder.utils.execute')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_allocate_file_blocks')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_set_volume_attributes')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_set_rw_permission')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_create_sparse_file')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.local_path')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_verify_gpfs_path_state')
    def test_create_volume_with_metadata(self,
                                         mock_gpfs_path_state,
                                         mock_local_path,
                                         mock_sparse_file,
                                         mock_rw_permission,
                                         mock_set_volume_attributes,
                                         mock_allocate_file_blocks,
                                         mock_exec):
        mock_local_path.return_value = 'test'
        volume = self._fake_volume()
        value = {}
        value['value'] = 'test'
        mock_set_volume_attributes.return_value = True
        metadata = {'fake_key': 'fake_value'}

        org_value = self.driver.configuration.gpfs_sparse_volumes
        self.override_config('gpfs_sparse_volumes', True,
                             conf.SHARED_CONF_GROUP)
        self.driver.create_volume(volume)
        self.assertTrue(self.driver._set_volume_attributes(volume, 'test',
                                                           metadata))
        self.override_config('gpfs_sparse_volumes', org_value,
                             conf.SHARED_CONF_GROUP)

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_resize_volume_file')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_set_volume_attributes')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._gpfs_redirect')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_set_rw_permission')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._create_gpfs_copy')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._gpfs_full_copy')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.'
                'GPFSDriver._get_snapshot_path')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.local_path')
    def test_create_volume_from_snapshot(self,
                                         mock_local_path,
                                         mock_snapshot_path,
                                         mock_gpfs_full_copy,
                                         mock_create_gpfs_copy,
                                         mock_rw_permission,
                                         mock_gpfs_redirect,
                                         mock_set_volume_attributes,
                                         mock_resize_volume_file):
        mock_resize_volume_file.return_value = 5 * units.Gi
        volume = self._fake_volume()
        volume['group_id'] = None
        self.driver.db = mock.Mock()
        self.driver.db.volume_get = mock.Mock()
        self.driver.db.volume_get.return_value = volume
        snapshot = self._fake_snapshot()
        mock_snapshot_path.return_value = "/tmp/fakepath"
        self.assertEqual({'size': 5.0},
                         self.driver.create_volume_from_snapshot(volume,
                                                                 snapshot))

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_resize_volume_file')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_set_volume_attributes')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._gpfs_redirect')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_set_rw_permission')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._create_gpfs_copy')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._gpfs_full_copy')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_get_snapshot_path')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.local_path')
    def test_create_volume_from_snapshot_metadata(self,
                                                  mock_local_path,
                                                  mock_snapshot_path,
                                                  mock_gpfs_full_copy,
                                                  mock_create_gpfs_copy,
                                                  mock_rw_permission,
                                                  mock_gpfs_redirect,
                                                  mock_set_volume_attributes,
                                                  mock_resize_volume_file):
        mock_resize_volume_file.return_value = 5 * units.Gi
        volume = self._fake_volume()
        volume['group_id'] = None
        self.driver.db = mock.Mock()
        self.driver.db.volume_get = mock.Mock()
        self.driver.db.volume_get.return_value = volume
        snapshot = self._fake_snapshot()
        mock_snapshot_path.return_value = "/tmp/fakepath"
        mock_set_volume_attributes.return_value = True
        metadata = {'fake_key': 'fake_value'}

        self.assertTrue(self.driver._set_volume_attributes(volume, 'test',
                                                           metadata))
        self.assertEqual({'size': 5.0},
                         self.driver.create_volume_from_snapshot(volume,
                                                                 snapshot))

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_resize_volume_file')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_set_volume_attributes')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_set_rw_permission')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_create_gpfs_clone')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._gpfs_full_copy')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.local_path')
    def test_create_cloned_volume(self,
                                  mock_local_path,
                                  mock_gpfs_full_copy,
                                  mock_create_gpfs_clone,
                                  mock_rw_permission,
                                  mock_set_volume_attributes,
                                  mock_resize_volume_file):
        mock_resize_volume_file.return_value = 5 * units.Gi
        volume = self._fake_volume()
        src_volume = self._fake_volume()
        self.assertEqual({'size': 5.0},
                         self.driver.create_cloned_volume(volume, src_volume))

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_resize_volume_file')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_set_volume_attributes')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_set_rw_permission')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_create_gpfs_clone')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._gpfs_full_copy')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.local_path')
    def test_create_cloned_volume_with_metadata(self,
                                                mock_local_path,
                                                mock_gpfs_full_copy,
                                                mock_create_gpfs_clone,
                                                mock_rw_permission,
                                                mock_set_volume_attributes,
                                                mock_resize_volume_file):
        mock_resize_volume_file.return_value = 5 * units.Gi
        volume = self._fake_volume()
        src_volume = self._fake_volume()
        mock_set_volume_attributes.return_value = True
        metadata = {'fake_key': 'fake_value'}

        self.assertTrue(self.driver._set_volume_attributes(volume, 'test',
                                                           metadata))
        self.assertEqual({'size': 5.0},
                         self.driver.create_cloned_volume(volume, src_volume))

    @mock.patch('cinder.utils.execute')
    def test_delete_gpfs_file_ok(self, mock_exec):
        mock_exec.side_effect = [('Parent  Depth   Parent inode   File name\n'
                                  '------  -----  --------------  ---------\n'
                                  '    no      2          148488  '
                                  '/gpfs0/test.txt', ''),
                                 ('', ''),
                                 ('', '')]
        self.driver._delete_gpfs_file(self.images_dir)
        self.driver._delete_gpfs_file(self.images_dir + '_')

        mock_exec.side_effect = [('Parent  Depth   Parent inode   File name\n'
                                  '------  -----  --------------  ---------\n'
                                  '                               '
                                  '/gpfs0/test.txt', ''),
                                 ('', '')]
        self.driver._delete_gpfs_file(self.images_dir)

    @mock.patch('os.path.exists')
    @mock.patch('cinder.utils.execute')
    def test_delete_gpfs_file_ok_parent(self, mock_exec, mock_path_exists):
        mock_path_exists.side_effect = [True, False, False,
                                        True, False, False,
                                        True, False, False]
        mock_exec.side_effect = [('Parent  Depth   Parent inode   File name\n'
                                  '------  -----  --------------  ---------\n'
                                  '    no      2          148488  '
                                  '/gpfs0/test.txt', ''),
                                 ('/gpfs0/test.snap\ntest', ''),
                                 ('', '')]
        self.driver._delete_gpfs_file(self.images_dir)
        mock_exec.side_effect = [('Parent  Depth   Parent inode   File name\n'
                                  '------  -----  --------------  ---------\n'
                                  '    no      2          148488  '
                                  '/gpfs0/test.txt', ''),
                                 ('/gpfs0/test.ts\ntest', ''),
                                 ('', '')]
        self.driver._delete_gpfs_file(self.images_dir)
        mock_exec.side_effect = [('Parent  Depth   Parent inode   File name\n'
                                  '------  -----  --------------  ---------\n'
                                  '    no      2          148488  '
                                  '/gpfs0/test.txt', ''),
                                 ('/gpfs0/test.txt\ntest', ''),
                                 ('', '')]
        self.driver._delete_gpfs_file(self.images_dir)

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._delete_gpfs_file')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.local_path')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_verify_gpfs_path_state')
    def test_delete_volume(self,
                           mock_verify_gpfs_path_state,
                           mock_local_path,
                           mock_delete_gpfs_file):
        self.driver.delete_volume('')

    @mock.patch('cinder.utils.execute')
    def test_gpfs_redirect_ok(self, mock_exec):
        org_value = self.driver.configuration.gpfs_max_clone_depth
        self.override_config('gpfs_max_clone_depth', 1, conf.SHARED_CONF_GROUP)
        mock_exec.side_effect = [('Parent  Depth   Parent inode   File name\n'
                                  '------  -----  --------------  ---------\n'
                                  '    no      2          148488  '
                                  '/gpfs0/test.txt', ''),
                                 ('', '')]
        self.assertTrue(self.driver._gpfs_redirect(''))
        self.override_config('gpfs_max_clone_depth', 1, conf.SHARED_CONF_GROUP)
        mock_exec.side_effect = [('Parent  Depth   Parent inode   File name\n'
                                  '------  -----  --------------  ---------\n'
                                  '    no      1          148488  '
                                  '/gpfs0/test.txt', ''),
                                 ('', '')]
        self.assertFalse(self.driver._gpfs_redirect(''))
        self.override_config('gpfs_max_clone_depth', org_value,
                             conf.SHARED_CONF_GROUP)

    @mock.patch('cinder.utils.execute')
    def test_gpfs_redirect_fail_depth(self, mock_exec):
        org_value = self.driver.configuration.gpfs_max_clone_depth
        self.override_config('gpfs_max_clone_depth', 0, conf.SHARED_CONF_GROUP)
        mock_exec.side_effect = [('Parent  Depth   Parent inode   File name\n'
                                  '------  -----  --------------  ---------\n'
                                  '    no      2          148488  '
                                  '/gpfs0/test.txt', ''),
                                 ('', '')]
        self.assertFalse(self.driver._gpfs_redirect(''))
        self.override_config('gpfs_max_clone_depth', org_value,
                             conf.SHARED_CONF_GROUP)

    @mock.patch('cinder.utils.execute')
    def test_gpfs_redirect_fail_match(self, mock_exec):
        org_value = self.driver.configuration.gpfs_max_clone_depth
        self.override_config('gpfs_max_clone_depth', 1, conf.SHARED_CONF_GROUP)
        mock_exec.side_effect = [('Parent  Depth   Parent inode   File name\n'
                                  '------  -----  --------------  ---------\n'
                                  '                       148488  '
                                  '/gpfs0/test.txt', ''),
                                 ('', '')]
        self.assertFalse(self.driver._gpfs_redirect(''))
        self.override_config('gpfs_max_clone_depth', org_value,
                             conf.SHARED_CONF_GROUP)

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._create_gpfs_snap')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._create_gpfs_copy')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._gpfs_redirect')
    @mock.patch('cinder.utils.execute')
    def test_create_gpfs_clone(self,
                               mock_exec,
                               mock_redirect,
                               mock_cr_gpfs_cp,
                               mock_cr_gpfs_snap):
        mock_redirect.return_value = True
        self.driver._create_gpfs_clone('', '')
        mock_redirect.side_effect = [True, False]
        self.driver._create_gpfs_clone('', '')

    @mock.patch('cinder.utils.execute')
    def test_create_gpfs_copy(self, mock_exec):
        self.driver._create_gpfs_copy('', '')

    @mock.patch('cinder.utils.execute')
    def test_create_gpfs_snap(self, mock_exec):
        self.driver._create_gpfs_snap('')
        self.driver._create_gpfs_snap('', '')

    @mock.patch('cinder.utils.execute')
    def test_is_gpfs_parent_file_ok(self, mock_exec):
        mock_exec.side_effect = [('Parent  Depth   Parent inode   File name\n'
                                  '------  -----  --------------  ---------\n'
                                  '   yes      2          148488  '
                                  '/gpfs0/test.txt', ''),
                                 ('Parent  Depth   Parent inode   File name\n'
                                  '------  -----  --------------  ---------\n'
                                  '    no      2          148488  '
                                  '/gpfs0/test.txt', '')]
        self.assertTrue(self.driver._is_gpfs_parent_file(''))
        self.assertFalse(self.driver._is_gpfs_parent_file(''))

    @mock.patch('cinder.objects.volume.Volume.get_by_id')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._gpfs_redirect')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_set_rw_permission')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._create_gpfs_snap')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.local_path')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_get_snapshot_path')
    def test_create_snapshot(self,
                             mock_get_snapshot_path,
                             mock_local_path,
                             mock_create_gpfs_snap,
                             mock_set_rw_permission,
                             mock_gpfs_redirect,
                             mock_vol_get_by_id):
        mock_get_snapshot_path.return_value = "/tmp/fakepath"

        vol = self._fake_volume()
        mock_vol_get_by_id.return_value = vol
        self.driver.create_snapshot(self._fake_snapshot())

    @mock.patch('cinder.utils.execute')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_get_snapshot_path')
    def test_delete_snapshot(self,
                             mock_snapshot_path,
                             mock_exec):
        snapshot = self._fake_snapshot()
        snapshot_path = "/tmp/fakepath"
        mock_snapshot_path.return_value = snapshot_path
        snapshot_ts_path = '%s.ts' % snapshot_path
        self.driver.delete_snapshot(snapshot)
        mock_exec.assert_any_call('mv', snapshot_path,
                                  snapshot_ts_path)
        mock_exec.assert_any_call('rm', '-f', snapshot_ts_path,
                                  check_exit_code=False)

    def test_ensure_export(self):
        self.assertIsNone(self.driver.ensure_export('', ''))

    def test_create_export(self):
        self.assertIsNone(self.driver.create_export('', '', {}))

    def test_remove_export(self):
        self.assertIsNone(self.driver.remove_export('', ''))

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.local_path')
    def test_initialize_connection(self, mock_local_path):
        volume = self._fake_volume()
        mock_local_path.return_value = "/tmp/fakepath"
        data = self.driver.initialize_connection(volume, '')
        self.assertEqual(volume.name, data['data']['name'])
        self.assertEqual("/tmp/fakepath", data['data']['device_path'])
        self.assertEqual('gpfs', data['driver_volume_type'])

    def test_terminate_connection(self):
        self.assertIsNone(self.driver.terminate_connection('', ''))

    def test_get_volume_stats(self):
        fake_avail = 80 * units.Gi
        fake_size = 2 * fake_avail
        with mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                        '_get_available_capacity',
                        return_value=(fake_avail, fake_size)):
            stats = self.driver.get_volume_stats()
            self.assertEqual('GPFS', stats['volume_backend_name'])
            self.assertEqual('file', stats['storage_protocol'])
            self.assertEqual('True', stats['gpfs_encryption_rest'])
            stats = self.driver.get_volume_stats(True)
            self.assertEqual('GPFS', stats['volume_backend_name'])
            self.assertEqual('file', stats['storage_protocol'])
            self.assertEqual('True', stats['gpfs_encryption_rest'])

    @mock.patch('cinder.utils.execute')
    def test_get_gpfs_encryption_status_true(self, mock_exec):
        mock_exec.return_value = ('mmlsfs::HEADER:version:reserved:reserved:'
                                  'deviceName:fieldName:data:remarks:\n'
                                  'mmlsfs::0:1:::gpfs:encryption:Yes:', '')
        self.assertEqual('Yes', self.driver._get_gpfs_encryption_status())

    @mock.patch('cinder.utils.execute')
    def test_get_gpfs_encryption_status_false(self, mock_exec):
        mock_exec.return_value = ('mmlsfs::HEADER:version:reserved:reserved:'
                                  'deviceName:fieldName:data:remarks:\n'
                                  'mmlsfs::0:1:::gpfs:encryption:No:', '')
        self.assertEqual('No', self.driver._get_gpfs_encryption_status())

    @mock.patch('cinder.utils.execute')
    def test_get_gpfs_encryption_status_fail(self, mock_exec):
        mock_exec.side_effect = (
            processutils.ProcessExecutionError(stdout='test', stderr='test'))
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._get_gpfs_encryption_status)

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_update_volume_stats')
    def test_get_volume_stats_none_stats(self, mock_upd_vol_stats):
        _stats_org = self.driver._stats
        self.driver._stats = mock.Mock()
        self.driver._stats.return_value = None
        self.driver.get_volume_stats()
        self.driver._stats = _stats_org

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._clone_image')
    def test_clone_image_pub(self, mock_exec):
        self.driver.clone_image('', '', '', {'id': 1}, '')

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._is_gpfs_path')
    def test_is_cloneable_ok(self, mock_is_gpfs_path):
        self.override_config('gpfs_images_share_mode', 'copy',
                             conf.SHARED_CONF_GROUP)
        self.override_config('gpfs_images_dir', self.images_dir,
                             conf.SHARED_CONF_GROUP)
        CONF.gpfs_images_dir = self.images_dir
        mock_is_gpfs_path.return_value = None
        self.assertEqual((True, None, os.path.join(CONF.gpfs_images_dir,
                                                   '12345')),
                         self.driver._is_cloneable('12345'))

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._is_gpfs_path')
    def test_is_cloneable_fail_path(self, mock_is_gpfs_path):
        self.override_config('gpfs_images_share_mode', 'copy',
                             conf.SHARED_CONF_GROUP)
        CONF.gpfs_images_dir = self.images_dir
        mock_is_gpfs_path.side_effect = (
            processutils.ProcessExecutionError(stdout='test', stderr='test'))
        self.assertNotEqual((True, None, os.path.join(CONF.gpfs_images_dir,
                                                      '12345')),
                            self.driver._is_cloneable('12345'))

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_resize_volume_file')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_set_rw_permission')
    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._create_gpfs_copy')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._create_gpfs_snap')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_is_gpfs_parent_file')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.local_path')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._is_cloneable')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_verify_gpfs_path_state')
    def test_clone_image_clonable(self,
                                  mock_verify_gpfs_path_state,
                                  mock_is_cloneable,
                                  mock_local_path,
                                  mock_is_gpfs_parent_file,
                                  mock_create_gpfs_snap,
                                  mock_qemu_img_info,
                                  mock_create_gpfs_copy,
                                  mock_conv_image,
                                  mock_set_rw_permission,
                                  mock_resize_volume_file):
        mock_is_cloneable.return_value = (True, 'test', self.images_dir)
        mock_is_gpfs_parent_file.return_value = False
        mock_qemu_img_info.return_value = self._fake_qemu_qcow2_image_info('')
        volume = self._fake_volume()
        self.assertEqual(({'provider_location': None}, True),
                         self.driver._clone_image(volume, '', 1))

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._is_cloneable')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver'
                '._verify_gpfs_path_state')
    def test_clone_image_not_cloneable(self,
                                       mock_verify_gpfs_path_state,
                                       mock_is_cloneable):
        mock_is_cloneable.return_value = (False, 'test', self.images_dir)
        volume = self._fake_volume()
        self.assertEqual((None, False),
                         self.driver._clone_image(volume, '', 1))

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_resize_volume_file')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_set_rw_permission')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._create_gpfs_copy')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._create_gpfs_snap')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_is_gpfs_parent_file')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.local_path')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._is_cloneable')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_verify_gpfs_path_state')
    def test_clone_image_format_raw_copy_on_write(self,
                                                  mock_verify_gpfs_path_state,
                                                  mock_is_cloneable,
                                                  mock_local_path,
                                                  mock_is_gpfs_parent_file,
                                                  mock_create_gpfs_snap,
                                                  mock_qemu_img_info,
                                                  mock_create_gpfs_copy,
                                                  mock_set_rw_permission,
                                                  mock_resize_volume_file):
        mock_is_cloneable.return_value = (True, 'test', self.images_dir)
        mock_local_path.return_value = self.volumes_path
        mock_is_gpfs_parent_file.return_value = False
        mock_qemu_img_info.return_value = self._fake_qemu_raw_image_info('')
        volume = self._fake_volume()
        org_value = self.driver.configuration.gpfs_images_share_mode
        self.override_config('gpfs_images_share_mode', 'copy_on_write',
                             conf.SHARED_CONF_GROUP)
        self.assertEqual(({'provider_location': None}, True),
                         self.driver._clone_image(volume, '', 1))
        mock_create_gpfs_snap.assert_called_once_with(self.images_dir)

        self.override_config('gpfs_images_share_mode', org_value,
                             conf.SHARED_CONF_GROUP)

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_resize_volume_file')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_set_rw_permission')
    @mock.patch('shutil.copyfile')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_is_gpfs_parent_file')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.local_path')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._is_cloneable')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_verify_gpfs_path_state')
    def test_clone_image_format_raw_copy(self,
                                         mock_verify_gpfs_path_state,
                                         mock_is_cloneable,
                                         mock_local_path,
                                         mock_is_gpfs_parent_file,
                                         mock_qemu_img_info,
                                         mock_copyfile,
                                         mock_set_rw_permission,
                                         mock_resize_volume_file):
        mock_is_cloneable.return_value = (True, 'test', self.images_dir)
        mock_local_path.return_value = self.volumes_path
        mock_qemu_img_info.return_value = self._fake_qemu_raw_image_info('')
        volume = self._fake_volume()
        org_value = self.driver.configuration.gpfs_images_share_mode

        self.override_config('gpfs_images_share_mode', 'copy',
                             conf.SHARED_CONF_GROUP)
        self.assertEqual(({'provider_location': None}, True),
                         self.driver._clone_image(volume, '', 1))
        mock_copyfile.assert_called_once_with(self.images_dir,
                                              self.volumes_path)

        self.override_config('gpfs_images_share_mode', org_value,
                             conf.SHARED_CONF_GROUP)

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_resize_volume_file')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_set_rw_permission')
    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.local_path')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._is_cloneable')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_verify_gpfs_path_state')
    def test_clone_image_format_qcow2(self,
                                      mock_verify_gpfs_path_state,
                                      mock_is_cloneable,
                                      mock_local_path,
                                      mock_qemu_img_info,
                                      mock_conv_image,
                                      mock_set_rw_permission,
                                      mock_resize_volume_file):
        mock_is_cloneable.return_value = (True, 'test', self.images_dir)
        mock_local_path.return_value = self.volumes_path
        mock_qemu_img_info.return_value = self._fake_qemu_qcow2_image_info('')
        volume = self._fake_volume()
        self.assertEqual(({'provider_location': None}, True),
                         self.driver._clone_image(volume, '', 1))
        mock_conv_image.assert_called_once_with(self.images_dir,
                                                self.volumes_path,
                                                'raw')

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_resize_volume_file')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.local_path')
    @mock.patch('cinder.image.image_utils.fetch_to_raw')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_verify_gpfs_path_state')
    def test_copy_image_to_volume(self,
                                  mock_verify_gpfs_path_state,
                                  mock_fetch_to_raw,
                                  mock_local_path,
                                  mock_resize_volume_file):
        volume = self._fake_volume()
        self.driver.copy_image_to_volume('', volume, '', 1)

    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.resize_image')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.local_path')
    def test_resize_volume_file_ok(self,
                                   mock_local_path,
                                   mock_resize_image,
                                   mock_qemu_img_info):
        volume = self._fake_volume()
        mock_qemu_img_info.return_value = self._fake_qemu_qcow2_image_info('')
        self.assertEqual(self._fake_qemu_qcow2_image_info('').virtual_size,
                         self.driver._resize_volume_file(volume, 2000))

    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.resize_image')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.local_path')
    def test_resize_volume_file_fail(self,
                                     mock_local_path,
                                     mock_resize_image,
                                     mock_qemu_img_info):
        volume = self._fake_volume()
        mock_resize_image.side_effect = (
            processutils.ProcessExecutionError(stdout='test', stderr='test'))
        mock_qemu_img_info.return_value = self._fake_qemu_qcow2_image_info('')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._resize_volume_file, volume, 2000)

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_resize_volume_file')
    def test_extend_volume(self, mock_resize_volume_file):
        volume = self._fake_volume()
        self.driver.extend_volume(volume, 2000)

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.local_path')
    @mock.patch('cinder.image.image_utils.upload_volume')
    def test_copy_volume_to_image(self, mock_upload_volume, mock_local_path):
        volume = test_utils.create_volume(
            self.context, volume_type_id=fake.VOLUME_TYPE_ID,
            updated_at=self.updated_at)
        extra_specs = {
            'image_service:store_id': 'fake-store'
        }
        test_utils.create_volume_type(
            self.context.elevated(), id=fake.VOLUME_TYPE_ID,
            name="test_type", extra_specs=extra_specs)

        self.driver.copy_volume_to_image('', volume, '', '')

    @mock.patch('cinder.utils.execute')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_get_volume_path')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_can_migrate_locally')
    def test_migrate_volume_ok(self, mock_local, volume_path, mock_exec):
        volume = self._fake_volume()
        host = {}
        host = {'host': 'foo', 'capabilities': {}}
        mock_local.return_value = (self.driver.configuration.
                                   gpfs_mount_point_base + '_')
        self.assertEqual((True, None),
                         self.driver._migrate_volume(volume, host))

    @mock.patch('cinder.utils.execute')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_can_migrate_locally')
    def test_migrate_volume_fail_dest_path(self, mock_local, mock_exec):
        volume = self._fake_volume()
        host = {}
        host = {'host': 'foo', 'capabilities': {}}
        mock_local.return_value = None
        self.assertEqual((False, None),
                         self.driver._migrate_volume(volume, host))

    @mock.patch('cinder.utils.execute')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_can_migrate_locally')
    def test_migrate_volume_fail_mpb(self, mock_local, mock_exec):
        volume = self._fake_volume()
        host = {}
        host = {'host': 'foo', 'capabilities': {}}
        mock_local.return_value = (self.driver.configuration.
                                   gpfs_mount_point_base)
        mock_exec.side_effect = (
            processutils.ProcessExecutionError(stdout='test', stderr='test'))
        self.assertEqual((True, None),
                         self.driver._migrate_volume(volume, host))

    @mock.patch('cinder.utils.execute')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_get_volume_path')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_can_migrate_locally')
    def test_migrate_volume_fail_mv(self, mock_local, mock_path, mock_exec):
        volume = self._fake_volume()
        host = {}
        host = {'host': 'foo', 'capabilities': {}}
        mock_local.return_value = (
            self.driver.configuration.gpfs_mount_point_base + '_')
        mock_exec.side_effect = (
            processutils.ProcessExecutionError(stdout='test', stderr='test'))
        self.assertEqual((False, None),
                         self.driver._migrate_volume(volume, host))

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._migrate_volume')
    def test_migrate_volume_ok_pub(self, mock_migrate_volume):
        self.driver.migrate_volume('', '', '')

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._migrate_volume')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_update_volume_storage_pool')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.local_path')
    @mock.patch('cinder.volume.drivers.ibm.gpfs._different')
    def test_retype_ok(self, mock_different, local_path,
                       mock_strg_pool, mock_migrate_vol):
        ctxt = self.context
        (volume, new_type, diff, host) = self._fake_retype_arguments()
        self.driver.db = mock.Mock()
        mock_different.side_effect = [False, True, True]
        mock_strg_pool.return_value = True
        mock_migrate_vol.return_value = (True, True)
        self.assertTrue(self.driver.retype(ctxt, volume, new_type, diff, host))

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._migrate_volume')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_update_volume_storage_pool')
    @mock.patch('cinder.volume.drivers.ibm.gpfs._different')
    def test_retype_diff_backend(self,
                                 mock_different,
                                 mock_strg_pool,
                                 mock_migrate_vol):
        ctxt = self.context
        (volume, new_type, diff, host) = self._fake_retype_arguments()
        mock_different.side_effect = [True, True, True]
        self.assertFalse(self.driver.retype(ctxt,
                                            volume,
                                            new_type,
                                            diff, host))

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._migrate_volume')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_update_volume_storage_pool')
    @mock.patch('cinder.volume.drivers.ibm.gpfs._different')
    def test_retype_diff_pools_migrated(self,
                                        mock_different,
                                        mock_strg_pool,
                                        mock_migrate_vol):
        ctxt = self.context
        (volume, new_type, diff, host) = self._fake_retype_arguments()
        self.driver.db = mock.Mock()
        mock_different.side_effect = [False, False, True]
        mock_strg_pool.return_value = True
        mock_migrate_vol.return_value = (True, True)
        self.assertTrue(self.driver.retype(ctxt, volume, new_type, diff, host))

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._migrate_volume')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_update_volume_storage_pool')
    @mock.patch('cinder.volume.drivers.ibm.gpfs._different')
    def test_retype_diff_pools(self,
                               mock_different,
                               mock_strg_pool,
                               mock_migrate_vol):
        ctxt = self.context
        (volume, new_type, diff, host) = self._fake_retype_arguments()
        mock_different.side_effect = [False, False, True]
        mock_strg_pool.return_value = True
        mock_migrate_vol.return_value = (False, False)
        self.assertFalse(self.driver.retype(ctxt,
                                            volume,
                                            new_type,
                                            diff,
                                            host))

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._migrate_volume')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_update_volume_storage_pool')
    @mock.patch('cinder.volume.drivers.ibm.gpfs._different')
    def test_retype_no_diff_hit(self,
                                mock_different,
                                mock_strg_pool,
                                mock_migrate_vol):
        ctxt = self.context
        (volume, new_type, diff, host) = self._fake_retype_arguments()
        mock_different.side_effect = [False, False, False]
        self.assertFalse(self.driver.retype(ctxt,
                                            volume,
                                            new_type,
                                            diff,
                                            host))

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.local_path')
    @mock.patch('cinder.utils.execute')
    def test_mkfs_ok(self, mock_exec, local_path):
        volume = self._fake_volume()
        self.driver._mkfs(volume, 'swap')
        self.driver._mkfs(volume, 'swap', 'test')
        self.driver._mkfs(volume, 'ext3', 'test')
        self.driver._mkfs(volume, 'vfat', 'test')

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.local_path')
    @mock.patch('cinder.utils.execute')
    def test_mkfs_fail_mk(self, mock_exec, local_path):
        volume = self._fake_volume()
        mock_exec.side_effect = (
            processutils.ProcessExecutionError(stdout='test', stderr='test'))
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._mkfs, volume, 'swap', 'test')

    @mock.patch('cinder.utils.execute')
    def test_get_available_capacity_ok(self, mock_exec):
        mock_exec.return_value = ('Filesystem         1-blocks      Used '
                                  'Available Capacity Mounted on\n'
                                  '/dev/gpfs            10737418240 544735232 '
                                  '10192683008       6%% /gpfs0', '')
        self.assertEqual((10192683008, 10737418240),
                         self.driver._get_available_capacity('/gpfs0'))

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_verify_gpfs_path_state')
    @mock.patch('cinder.utils.execute')
    def test_get_available_capacity_fail_mounted(self,
                                                 mock_exec,
                                                 mock_path_state):
        mock_path_state.side_effect = (
            exception.VolumeBackendAPIException('test'))
        mock_exec.return_value = ('Filesystem         1-blocks      Used '
                                  'Available Capacity Mounted on\n'
                                  '/dev/gpfs            10737418240 544735232 '
                                  '10192683008       6%% /gpfs0', '')
        self.assertEqual((0, 0), self.driver._get_available_capacity('/gpfs0'))

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._is_gpfs_path')
    def test_verify_gpfs_path_state_ok(self, mock_is_gpfs_path):
        self.driver._verify_gpfs_path_state(self.images_dir)

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver._is_gpfs_path')
    def test_verify_gpfs_path_state_fail_path(self, mock_is_gpfs_path):
        mock_is_gpfs_path.side_effect = (
            processutils.ProcessExecutionError(stdout='test', stderr='test'))
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._verify_gpfs_path_state, self.images_dir)

    @mock.patch('cinder.utils.execute')
    def test_create_consistencygroup(self, mock_exec):
        ctxt = self.context
        group = self._fake_group()
        self.driver._create_consistencygroup(ctxt, group)
        fsdev = self.driver._gpfs_device
        cgname = "consisgroup-%s" % group['id']
        cgpath = os.path.join(self.driver.configuration.gpfs_mount_point_base,
                              cgname)
        cmd = ['mmcrfileset', fsdev, cgname, '--inode-space', 'new']
        mock_exec.assert_any_call(*cmd)
        cmd = ['mmlinkfileset', fsdev, cgname, '-J', cgpath]
        mock_exec.assert_any_call(*cmd)
        cmd = ['chmod', '770', cgpath]
        mock_exec.assert_any_call(*cmd)

    @mock.patch('cinder.utils.execute')
    def test_create_consistencygroup_fail(self, mock_exec):
        ctxt = self.context
        group = self._fake_group()
        mock_exec.side_effect = (
            processutils.ProcessExecutionError(stdout='test', stderr='test'))
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._create_consistencygroup, ctxt, group)

    @mock.patch('cinder.utils.execute')
    def test_delete_consistencygroup(self, mock_exec):
        ctxt = self.context
        group = self._fake_group()
        group['status'] = fields.ConsistencyGroupStatus.AVAILABLE
        volume = self._fake_volume()
        volume['status'] = 'available'
        volumes = []
        volumes.append(volume)
        self.driver.db = mock.Mock()
        self.driver.db.volume_get_all_by_group = mock.Mock()
        self.driver.db.volume_get_all_by_group.return_value = volumes

        self.driver._delete_consistencygroup(ctxt, group, [])
        fsdev = self.driver._gpfs_device
        cgname = "consisgroup-%s" % group['id']
        cmd = ['mmlsfileset', fsdev, cgname]
        mock_exec.assert_any_call(*cmd)
        cmd = ['mmunlinkfileset', fsdev, cgname, '-f']
        mock_exec.assert_any_call(*cmd)
        cmd = ['mmdelfileset', fsdev, cgname, '-f']
        mock_exec.assert_any_call(*cmd)

    @mock.patch('cinder.utils.execute')
    def test_delete_consistencygroup_no_fileset(self, mock_exec):
        ctxt = self.context
        group = self._fake_group()
        group['status'] = fields.ConsistencyGroupStatus.AVAILABLE
        volume = self._fake_volume()
        volume['status'] = 'available'
        volumes = []
        volumes.append(volume)
        self.driver.db = mock.Mock()
        self.driver.db.volume_get_all_by_group = mock.Mock()
        self.driver.db.volume_get_all_by_group.return_value = volumes
        mock_exec.side_effect = (
            processutils.ProcessExecutionError(exit_code=2))

        self.driver._delete_consistencygroup(ctxt, group, [])
        fsdev = self.driver._gpfs_device
        cgname = "consisgroup-%s" % group['id']
        cmd = ['mmlsfileset', fsdev, cgname]
        mock_exec.assert_called_once_with(*cmd)

    @mock.patch('cinder.utils.execute')
    def test_delete_consistencygroup_fail(self, mock_exec):
        ctxt = self.context
        group = self._fake_group()
        group['status'] = fields.ConsistencyGroupStatus.AVAILABLE
        self.driver.db = mock.Mock()
        self.driver.db.volume_get_all_by_group = mock.Mock()
        self.driver.db.volume_get_all_by_group.return_value = []

        mock_exec.side_effect = (
            processutils.ProcessExecutionError(stdout='test', stderr='test'))
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._delete_consistencygroup,
                          ctxt, group, [])

    def test_update_consistencygroup(self):
        ctxt = self.context
        group = self._fake_group()
        self.assertRaises(gpfs.GPFSDriverUnsupportedOperation,
                          self.driver._update_consistencygroup, ctxt, group)

    def test_create_consisgroup_from_src(self):
        ctxt = self.context
        group = self._fake_group()
        self.assertRaises(gpfs.GPFSDriverUnsupportedOperation,
                          self.driver._create_consistencygroup_from_src,
                          ctxt, group, [])

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.create_snapshot')
    def test_create_cgsnapshot(self, mock_create_snap):
        ctxt = self.context
        cgsnap = self._fake_cgsnapshot()
        snapshot1 = self._fake_snapshot()
        model_update, snapshots = self.driver._create_cgsnapshot(ctxt, cgsnap,
                                                                 [snapshot1])
        self.driver.create_snapshot.assert_called_once_with(snapshot1)
        self.assertEqual({'status': fields.ConsistencyGroupStatus.AVAILABLE},
                         model_update)
        self.assertEqual({'id': snapshot1.id,
                         'status': fields.SnapshotStatus.AVAILABLE},
                         snapshots[0])

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.create_snapshot')
    def test_create_cgsnapshot_empty(self, mock_create_snap):
        ctxt = self.context
        cgsnap = self._fake_cgsnapshot()
        model_update, snapshots = self.driver._create_cgsnapshot(ctxt, cgsnap,
                                                                 [])
        self.assertFalse(self.driver.create_snapshot.called)
        self.assertEqual({'status': fields.ConsistencyGroupStatus.AVAILABLE},
                         model_update)

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.delete_snapshot')
    def test_delete_cgsnapshot(self, mock_delete_snap):
        ctxt = self.context
        cgsnap = self._fake_cgsnapshot()
        snapshot1 = self._fake_snapshot()
        model_update, snapshots = self.driver._delete_cgsnapshot(ctxt, cgsnap,
                                                                 [snapshot1])
        self.driver.delete_snapshot.assert_called_once_with(snapshot1)
        self.assertEqual({'status': fields.ConsistencyGroupStatus.DELETED},
                         model_update)
        self.assertEqual({'id': snapshot1.id,
                         'status': fields.SnapshotStatus.DELETED},
                         snapshots[0])

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.delete_snapshot')
    def test_delete_cgsnapshot_empty(self, mock_delete_snap):
        ctxt = self.context
        cgsnap = self._fake_cgsnapshot()
        model_update, snapshots = self.driver._delete_cgsnapshot(ctxt, cgsnap,
                                                                 [])
        self.assertFalse(self.driver.delete_snapshot.called)
        self.assertEqual({'status': fields.ConsistencyGroupStatus.DELETED},
                         model_update)

    def test_local_path_volume_not_in_cg(self):
        volume = self._fake_volume()
        volume['group_id'] = None
        volume_path = os.path.join(
            self.driver.configuration.gpfs_mount_point_base,
            volume['name']
        )
        ret = self.driver.local_path(volume)
        self.assertEqual(volume_path, ret)

    @mock.patch('cinder.db.get_by_id')
    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type')
    def test_local_path_volume_in_cg(self, mock_group_cg_snapshot_type,
                                     mock_group_obj):
        mock_group_cg_snapshot_type.return_value = True
        volume = self._fake_volume()
        group = self._fake_group()
        mock_group_obj.return_value = group
        cgname = "consisgroup-%s" % volume['group_id']
        volume_path = os.path.join(
            self.driver.configuration.gpfs_mount_point_base,
            cgname,
            volume['name']
        )
        ret = self.driver.local_path(volume)
        self.assertEqual(volume_path, ret)

    @mock.patch('cinder.context.get_admin_context')
    @mock.patch('cinder.objects.volume.Volume.get_by_id')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.local_path')
    def test_get_snapshot_path(self, mock_local_path, mock_vol_get_by_id,
                               mock_admin_context):
        volume = self._fake_volume()
        mock_vol_get_by_id.return_value = volume
        volume_path = self.volumes_path
        mock_local_path.return_value = volume_path
        snapshot = self._fake_snapshot()
        ret = self.driver._get_snapshot_path(snapshot)
        self.assertEqual(
            os.path.join(os.path.dirname(volume_path), snapshot.name), ret
        )

    @mock.patch('cinder.utils.execute')
    def test_gpfs_full_copy(self, mock_exec):
        src = "/tmp/vol1"
        dest = "/tmp/vol2"
        self.driver._gpfs_full_copy(src, dest)
        mock_exec.assert_called_once_with('cp', src, dest,
                                          check_exit_code=True)

    def _fake_volume(self):
        volume = {}
        volume['id'] = fake.VOLUME_ID
        volume['display_name'] = 'test'
        volume['metadata'] = {'key1': 'val1'}
        volume['_name_id'] = None
        volume['size'] = 1000
        volume['group_id'] = fake.CONSISTENCY_GROUP_ID

        return objects.Volume(self.context, **volume)

    def _fake_snapshot(self):
        snapshot = {}
        snapshot['id'] = fake.SNAPSHOT_ID
        snapshot['display_name'] = 'test-snap'
        snapshot['volume_size'] = 1000
        snapshot['volume_id'] = fake.VOLUME_ID
        snapshot['status'] = 'available'
        snapshot['snapshot_metadata'] = []

        return objects.Snapshot(context=self.context, **snapshot)

    def _fake_volume_in_cg(self):
        volume = self._fake_volume()
        volume.group_id = fake.CONSISTENCY_GROUP_ID
        return volume

    def _fake_group(self):
        group = {}
        group['name'] = 'test_group'
        group['id'] = fake.CONSISTENCY_GROUP_ID
        group['user_id'] = fake.USER_ID
        group['group_type_id'] = fake.GROUP_TYPE_ID
        group['project_id'] = fake.PROJECT_ID

        return objects.Group(self.context, **group)

    def _fake_cgsnapshot(self):
        snapshot = self._fake_snapshot()
        snapshot.group_id = fake.CONSISTENCY_GROUP_ID
        return snapshot

    def _fake_qemu_qcow2_image_info(self, path):
        data = FakeQemuImgInfo()
        data.file_format = 'qcow2'
        data.backing_file = None
        data.virtual_size = 1 * units.Gi
        return data

    def _fake_qemu_raw_image_info(self, path):
        data = FakeQemuImgInfo()
        data.file_format = 'raw'
        data.backing_file = None
        data.virtual_size = 1 * units.Gi
        return data

    def _fake_retype_arguments(self):
        ctxt = self.context
        loc = 'GPFSDriver:%s:testpath' % self.driver._cluster_id
        cap = {'location_info': loc}
        host = {'host': 'foo', 'capabilities': cap}
        key_specs_old = {'capabilities:storage_pool': 'bronze',
                         'volume_backend_name': 'backend1'}
        key_specs_new = {'capabilities:storage_pool': 'gold',
                         'volume_backend_name': 'backend1'}
        old_type_ref = volume_types.create(ctxt, 'old', key_specs_old)
        new_type_ref = volume_types.create(ctxt, 'new', key_specs_new)

        volume_types.get_volume_type(ctxt, old_type_ref['id'])
        new_type = volume_types.get_volume_type(ctxt, new_type_ref['id'])

        diff, _equal = volume_types.volume_types_diff(ctxt,
                                                      old_type_ref['id'],
                                                      new_type_ref['id'])

        volume = self._fake_volume()
        volume['host'] = 'foo'

        return (volume, new_type, diff, host)

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type')
    def test_create_group(self, mock_cg_snapshot_type):
        mock_cg_snapshot_type.return_value = False
        ctxt = self.context
        group = self._fake_group()
        self.assertRaises(
            NotImplementedError,
            self.driver.create_group,
            ctxt, group
        )

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_create_consistencygroup')
    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type')
    def test_create_group_cg(self, mock_cg_snapshot_type,
                             mock_consisgroup_create):
        mock_cg_snapshot_type.return_value = True
        ctxt = self.context
        group = self._fake_group()
        self.driver.create_group(ctxt, group)
        mock_consisgroup_create.assert_called_once_with(ctxt, group)

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type')
    def test_delete_group(self, mock_cg_snapshot_type):
        mock_cg_snapshot_type.return_value = False
        ctxt = self.context
        group = self._fake_group()
        volumes = []
        self.assertRaises(
            NotImplementedError,
            self.driver.delete_group,
            ctxt, group, volumes
        )

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_delete_consistencygroup')
    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type')
    def test_delete_group_cg(self, mock_cg_snapshot_type,
                             mock_consisgroup_delete):
        mock_cg_snapshot_type.return_value = True
        ctxt = self.context
        group = self._fake_group()
        volumes = []
        self.driver.delete_group(ctxt, group, volumes)
        mock_consisgroup_delete.assert_called_once_with(ctxt, group, volumes)

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type')
    def test_update_group(self, mock_cg_snapshot_type):
        mock_cg_snapshot_type.return_value = False
        ctxt = self.context
        group = self._fake_group()
        self.assertRaises(
            NotImplementedError,
            self.driver.update_group,
            ctxt, group
        )

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_update_consistencygroup')
    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type')
    def test_update_group_cg(self, mock_cg_snapshot_type,
                             mock_consisgroup_update):
        mock_cg_snapshot_type.return_value = True
        ctxt = self.context
        group = self._fake_group()
        self.driver.update_group(ctxt, group)
        mock_consisgroup_update.assert_called_once_with(ctxt, group,
                                                        None, None)

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type')
    def test_create_group_snapshot(self, mock_cg_snapshot_type):
        mock_cg_snapshot_type.return_value = False
        ctxt = self.context
        group_snapshot = mock.MagicMock()
        snapshots = [mock.Mock()]
        self.assertRaises(
            NotImplementedError,
            self.driver.create_group_snapshot,
            ctxt, group_snapshot, snapshots
        )

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_create_cgsnapshot')
    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type')
    def test_create_group_snapshot_cg(self, mock_cg_snapshot_type,
                                      mock_cgsnapshot_create):
        mock_cg_snapshot_type.return_value = True
        ctxt = self.context
        group_snapshot = mock.MagicMock()
        snapshots = [mock.Mock()]
        self.driver.create_group_snapshot(ctxt, group_snapshot, snapshots)
        mock_cgsnapshot_create.assert_called_once_with(ctxt, group_snapshot,
                                                       snapshots)

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type')
    def test_delete_group_snapshot(self, mock_cg_snapshot_type):
        mock_cg_snapshot_type.return_value = False
        ctxt = self.context
        group_snapshot = mock.MagicMock()
        snapshots = [mock.Mock()]
        self.assertRaises(
            NotImplementedError,
            self.driver.delete_group_snapshot,
            ctxt, group_snapshot, snapshots
        )

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_delete_cgsnapshot')
    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type')
    def test_delete_group_snapshot_cg(self, mock_cg_snapshot_type,
                                      mock_cgsnapshot_delete):
        mock_cg_snapshot_type.return_value = True
        ctxt = self.context
        group_snapshot = mock.MagicMock()
        snapshots = [mock.Mock()]
        self.driver.delete_group_snapshot(ctxt, group_snapshot, snapshots)
        mock_cgsnapshot_delete.assert_called_once_with(ctxt, group_snapshot,
                                                       snapshots)

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type')
    def test_create_group_from_src(self, mock_cg_snapshot_type):
        mock_cg_snapshot_type.return_value = False
        ctxt = self.context
        group = self._fake_group()
        volumes = []
        self.assertRaises(
            NotImplementedError,
            self.driver.create_group_from_src,
            ctxt, group, volumes
        )

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_create_consistencygroup_from_src')
    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type')
    def test_create_group_from_src_cg(self, mock_cg_snapshot_type,
                                      mock_cg_clone_create):
        mock_cg_snapshot_type.return_value = True
        ctxt = self.context
        group = self._fake_group()
        volumes = []
        self.driver.create_group_from_src(ctxt, group, volumes)
        mock_cg_clone_create.assert_called_once_with(ctxt, group, volumes,
                                                     None, None, None, None)


class GPFSRemoteDriverTestCase(test.TestCase):
    """Unit tests for GPFSRemoteDriver class"""
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSRemoteDriver.'
                '_get_active_gpfs_node_ip')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSRemoteDriver.'
                '_run_ssh')
    def test_gpfs_remote_execute(self,
                                 mock_run_ssh,
                                 mock_active_gpfs_ip):
        configuration = conf.Configuration(None)
        self.driver = gpfs.GPFSRemoteDriver(configuration=configuration)
        self.driver._gpfs_remote_execute('test', check_exit_code=True)
        expected = [mock.call(('test',), True)]
        self.assertEqual(expected, mock_run_ssh.mock_calls)

    @mock.patch('paramiko.SSHClient', new=mock.MagicMock())
    @mock.patch('os.path.isfile', return_value=True)
    @mock.patch('six.moves.builtins.open')
    @mock.patch('os.path.expanduser')
    @mock.patch('paramiko.RSAKey.from_private_key_file')
    @mock.patch('oslo_concurrency.processutils.ssh_execute')
    def test_get_active_gpfs_node_ip(self, mock_ssh_execute,
                                     mock_pkey_file, mock_path,
                                     mock_open, mock_isfile):
        configuration = conf.Configuration(None)
        configuration.gpfs_hosts = ['10.0.0.1', '10.0.0.2']
        configuration.gpfs_mount_point_base = '/gpfs'
        configuration.gpfs_private_key = '/test/fake_private_key'
        mmgetstate_fake_out = "mmgetstate::state:\nmmgetstate::active:"
        mock_ssh_execute.side_effect = [(mmgetstate_fake_out, ''), ('', '')]
        self.driver = gpfs.GPFSRemoteDriver(configuration=configuration)
        san_ip = self.driver._get_active_gpfs_node_ip()
        self.assertEqual('10.0.0.1', san_ip)

    @mock.patch('paramiko.SSHClient', new=mock.MagicMock())
    @mock.patch('os.path.isfile', return_value=True)
    @mock.patch('six.moves.builtins.open')
    @mock.patch('os.path.expanduser')
    @mock.patch('paramiko.RSAKey.from_private_key_file')
    @mock.patch('oslo_concurrency.processutils.ssh_execute')
    def test_get_active_gpfs_node_ip_with_password(self, mock_ssh_execute,
                                                   mock_pkey_file, mock_path,
                                                   mock_open, mock_isfile):
        configuration = conf.Configuration(None)
        configuration.gpfs_hosts = ['10.0.0.1', '10.0.0.2']
        configuration.gpfs_mount_point_base = '/gpfs'
        configuration.gpfs_user_password = 'FakePassword'
        mmgetstate_fake_out = "mmgetstate::state:\nmmgetstate::active:"
        mock_ssh_execute.side_effect = [(mmgetstate_fake_out, ''), ('', '')]
        self.driver = gpfs.GPFSRemoteDriver(configuration=configuration)
        san_ip = self.driver._get_active_gpfs_node_ip()
        self.assertEqual('10.0.0.1', san_ip)

    @mock.patch('paramiko.SSHClient', new=mock.MagicMock())
    @mock.patch('os.path.isfile', return_value=True)
    @mock.patch('six.moves.builtins.open')
    def test_get_active_gpfs_node_ip_missing_key_and_password(self, mock_open,
                                                              mock_isfile):
        configuration = conf.Configuration(None)
        configuration.gpfs_hosts = ['10.0.0.1', '10.0.0.2']
        configuration.gpfs_mount_point_base = '/gpfs'
        self.driver = gpfs.GPFSRemoteDriver(configuration=configuration)
        self.assertRaises(exception.VolumeDriverException,
                          self.driver._get_active_gpfs_node_ip)

    @mock.patch('paramiko.SSHClient', new=mock.MagicMock())
    @mock.patch('os.path.isfile', return_value=True)
    @mock.patch('six.moves.builtins.open')
    @mock.patch('os.path.expanduser')
    @mock.patch('paramiko.RSAKey.from_private_key_file')
    @mock.patch('oslo_concurrency.processutils.ssh_execute')
    def test_get_active_gpfs_node_ip_second(self, mock_ssh_execute,
                                            mock_pkey_file, mock_path,
                                            mock_open, mock_isfile):
        configuration = conf.Configuration(None)
        configuration.gpfs_hosts = ['10.0.0.1', '10.0.0.2']
        configuration.gpfs_mount_point_base = '/gpfs'
        configuration.gpfs_private_key = '/test/fake_private_key'
        mmgetstate_active_fake_out = "mmgetstate::state:\nmmgetstate::active:"
        mmgetstate_down_fake_out = "mmgetstate::state:\nmmgetstate::down:"
        mock_ssh_execute.side_effect = [(mmgetstate_down_fake_out, ''),
                                        (mmgetstate_active_fake_out, ''),
                                        ('', '')]
        self.driver = gpfs.GPFSRemoteDriver(configuration=configuration)
        san_ip = self.driver._get_active_gpfs_node_ip()
        self.assertEqual('10.0.0.2', san_ip)

    @mock.patch('paramiko.SSHClient', new=mock.MagicMock())
    def test_missing_ssh_host_key_config(self):
        configuration = conf.Configuration(None)
        configuration.gpfs_hosts = ['10.0.0.1', '10.0.0.2']
        configuration.gpfs_hosts_key_file = None
        self.driver = gpfs.GPFSRemoteDriver(configuration=configuration)
        self.assertRaises(exception.ParameterNotFound,
                          self.driver._get_active_gpfs_node_ip)

    @mock.patch('paramiko.SSHClient', new=mock.MagicMock())
    @mock.patch('os.path.isfile', return_value=False)
    def test_init_missing_ssh_host_key_file(self,
                                            mock_is_file):
        configuration = conf.Configuration(None)
        configuration.gpfs_hosts = ['10.0.0.1', '10.0.0.2']
        configuration.gpfs_hosts_key_file = '/test'
        self.flags(state_path='/var/lib/cinder')
        self.driver = gpfs.GPFSRemoteDriver(configuration=configuration)
        self.assertRaises(exception.InvalidInput,
                          self.driver._get_active_gpfs_node_ip)

    @mock.patch('paramiko.SSHClient', new=mock.MagicMock())
    @mock.patch('os.path.isfile', return_value=True)
    @mock.patch('six.moves.builtins.open')
    @mock.patch('os.path.expanduser')
    @mock.patch('paramiko.RSAKey.from_private_key_file')
    @mock.patch('oslo_concurrency.processutils.ssh_execute')
    def test_get_active_gpfs_node_ip_exception(self, mock_ssh_execute,
                                               mock_pkey_file, mock_path,
                                               mock_open, mock_isfile):
        configuration = conf.Configuration(None)
        configuration.gpfs_hosts = ['10.0.0.1', '10.0.0.2']
        configuration.gpfs_mount_point_base = '/gpfs'
        configuration.gpfs_private_key = "/test/fake_private_key"
        mmgetstate_down_fake_out = "mmgetstate::state:\nmmgetstate::down:"
        mock_ssh_execute.side_effect = [(mmgetstate_down_fake_out, ''),
                                        processutils.ProcessExecutionError(
                                        stderr='test')]
        self.driver = gpfs.GPFSRemoteDriver(configuration=configuration)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._get_active_gpfs_node_ip)


class GPFSNFSDriverTestCase(test.TestCase):
    driver_name = "cinder.volume.drivers.gpfs.GPFSNFSDriver"
    TEST_NFS_EXPORT = 'nfs-host1:/export'
    TEST_SIZE_IN_GB = 1
    TEST_EXTEND_SIZE_IN_GB = 2
    TEST_MNT_POINT = '/mnt/nfs'
    TEST_MNT_POINT_BASE = '/mnt'
    TEST_GPFS_MNT_POINT_BASE = '/export'
    TEST_LOCAL_PATH = '/mnt/nfs/volume-123'
    TEST_VOLUME_PATH = '/export/volume-123'
    TEST_SNAP_PATH = '/export/snapshot-123'

    def _execute_wrapper(self, cmd, *args, **kwargs):
        try:
            kwargs.pop('run_as_root')
        except KeyError:
            pass

        return utils.execute(cmd, *args, **kwargs)

    def _fake_volume(self):
        volume = {}
        volume['id'] = fake.VOLUME_ID
        volume['display_name'] = 'test'
        volume['metadata'] = {'key1': 'val1'}
        volume['_name_id'] = None
        volume['size'] = 1000
        volume['group_id'] = fake.CONSISTENCY_GROUP_ID

        return objects.Volume(self.context, **volume)

    def _fake_group(self):
        group = {}
        group['name'] = 'test_group'
        group['id'] = fake.CONSISTENCY_GROUP_ID
        group['user_id'] = fake.USER_ID
        group['group_type_id'] = fake.GROUP_TYPE_ID
        group['project_id'] = fake.PROJECT_ID

        return objects.Group(self.context, **group)

    def _fake_snapshot(self):
        snapshot = {}
        snapshot['id'] = '12345'
        snapshot['name'] = 'test-snap'
        snapshot['volume_size'] = 1000
        snapshot['volume_id'] = '123456'
        snapshot['status'] = 'available'
        return snapshot

    def setUp(self):
        super(GPFSNFSDriverTestCase, self).setUp()
        self.driver = gpfs.GPFSNFSDriver(configuration=conf.
                                         Configuration(None))
        self.driver.gpfs_execute = self._execute_wrapper
        self.context = context.get_admin_context()
        self.context.user_id = 'fake'
        self.context.project_id = 'fake'

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSNFSDriver.'
                '_run_ssh')
    def test_gpfs_remote_execute(self, mock_run_ssh):
        mock_run_ssh.return_value = 'test'
        self.driver._gpfs_remote_execute('test', check_exit_code=True)
        expected = [mock.call(('test',), True)]
        self.assertEqual(expected, mock_run_ssh.mock_calls)

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSNFSDriver.'
                '_ensure_shares_mounted')
    def test_update_volume_stats(self, mock_ensure):
        """Check update volume stats."""

        mock_ensure.return_value = True
        fake_avail = 80 * units.Gi
        fake_size = 2 * fake_avail
        fake_used = 10 * units.Gi

        with mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSNFSDriver.'
                        '_get_capacity_info',
                        return_value=(fake_avail, fake_size, fake_used)):
            stats = self.driver.get_volume_stats()
            self.assertEqual('GPFSNFS', stats['volume_backend_name'])
            self.assertEqual('file', stats['storage_protocol'])
            stats = self.driver.get_volume_stats(True)
            self.assertEqual('GPFSNFS', stats['volume_backend_name'])
            self.assertEqual('file', stats['storage_protocol'])

    @mock.patch('cinder.db.get_by_id')
    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type')
    def test_get_volume_path(self, mock_group_cg_snapshot_type, mock_group):
        mock_group_cg_snapshot_type.return_value = True
        self.driver.configuration.gpfs_mount_point_base = (
            self.TEST_GPFS_MNT_POINT_BASE)
        volume = self._fake_volume()
        group = self._fake_group()
        mock_group.return_value = group
        volume_path_in_cg = os.path.join(self.TEST_GPFS_MNT_POINT_BASE,
                                         'consisgroup-' +
                                         fake.CONSISTENCY_GROUP_ID,
                                         'volume-' + fake.VOLUME_ID)
        self.assertEqual(volume_path_in_cg,
                         self.driver._get_volume_path(volume))
        volume.group_id = None
        volume_path = os.path.join(self.TEST_GPFS_MNT_POINT_BASE,
                                   'volume-' + fake.VOLUME_ID)
        self.assertEqual(volume_path,
                         self.driver._get_volume_path(volume))

    @mock.patch('cinder.db.get_by_id')
    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSNFSDriver.'
                '_get_mount_point_for_share')
    def test_local_path(self, mock_mount_point,
                        mock_group_cg_snapshot_type,
                        mock_group):
        mock_mount_point.return_value = self.TEST_MNT_POINT_BASE
        mock_group_cg_snapshot_type.return_value = True
        volume = self._fake_volume()
        group = self._fake_group()
        mock_group.return_value = group
        volume['provider_location'] = self.TEST_MNT_POINT_BASE
        local_volume_path_in_cg = os.path.join(self.TEST_MNT_POINT_BASE,
                                               'consisgroup-' +
                                               fake.CONSISTENCY_GROUP_ID,
                                               'volume-' + fake.VOLUME_ID)
        self.assertEqual(local_volume_path_in_cg,
                         self.driver.local_path(volume))
        volume.group_id = None
        local_volume_path = os.path.join(self.TEST_MNT_POINT_BASE,
                                         'volume-' + fake.VOLUME_ID)
        self.assertEqual(local_volume_path,
                         self.driver.local_path(volume))

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSNFSDriver.'
                '_get_volume_path')
    def test_get_snapshot_path(self, mock_volume_path):
        volume = self._fake_volume()
        self.driver.db = mock.Mock()
        self.driver.db.volume_get = mock.Mock()
        self.driver.db.volume_get.return_value = volume
        mock_volume_path.return_value = os.path.join(self.
                                                     TEST_GPFS_MNT_POINT_BASE,
                                                     volume['name'])
        snapshot = self._fake_snapshot()
        self.assertEqual('/export/test-snap',
                         self.driver._get_snapshot_path(snapshot))

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSNFSDriver.'
                '_find_share')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                'create_volume')
    def test_create_volume(self,
                           mock_create_volume,
                           mock_find_share):
        volume = self._fake_volume()
        mock_find_share.return_value = self.TEST_VOLUME_PATH
        self.assertEqual({'provider_location': self.TEST_VOLUME_PATH},
                         self.driver.create_volume(volume))

    @mock.patch('os.path.dirname')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_delete_gpfs_file')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSNFSDriver.'
                'local_path')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSNFSDriver.'
                '_get_volume_path')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_verify_gpfs_path_state')
    def test_delete_volume(self,
                           mock_verify_gpfs_path_state,
                           mock_volume_path,
                           mock_local_path,
                           mock_delete_gpfs_file,
                           mock_dirname):
        mock_dirname.return_value = '/a/dir/'
        self.driver.delete_volume('')

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                'delete_snapshot')
    def test_delete_snapshot(self,
                             mock_delete_snapshot):
        self.driver.delete_snapshot('')

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_resize_volume_file')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSNFSDriver.'
                '_find_share')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_create_volume_from_snapshot')
    def test_create_volume_from_snapshot(self,
                                         mock_create_volume_from_snapshot,
                                         mock_find_share,
                                         mock_resize_volume_file):
        volume = self._fake_volume()
        snapshot = self._fake_snapshot()
        mock_find_share.return_value = self.TEST_VOLUME_PATH
        self.assertEqual({'provider_location': self.TEST_VOLUME_PATH},
                         self.driver.create_volume_from_snapshot(volume,
                                                                 snapshot))

    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_resize_volume_file')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSNFSDriver.'
                '_find_share')
    @mock.patch('cinder.volume.drivers.ibm.gpfs.GPFSDriver.'
                '_create_cloned_volume')
    def test_create_cloned_volume(self,
                                  mock_create_cloned_volume,
                                  mock_find_share,
                                  mock_resize_volume_file):
        volume = self._fake_volume()
        src_vref = self._fake_volume()
        mock_find_share.return_value = self.TEST_VOLUME_PATH
        self.assertEqual({'provider_location': self.TEST_VOLUME_PATH},
                         self.driver.create_cloned_volume(volume, src_vref))
