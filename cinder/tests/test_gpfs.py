# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import mox as mox_lib
import os
import tempfile

from oslo.config import cfg

from cinder import context
from cinder import db
from cinder import exception
from cinder.image import image_utils
from cinder.openstack.common import imageutils
from cinder.openstack.common import importutils
from cinder.openstack.common import log as logging
from cinder.openstack.common import processutils
from cinder import test
from cinder.tests import utils as test_utils
from cinder import units
from cinder import utils
from cinder.volume import configuration as conf
from cinder.volume.drivers.gpfs import GPFSDriver

LOG = logging.getLogger(__name__)

CONF = cfg.CONF


class FakeImageService():
    def update(self, context, image_id, path):
        pass

    def show(self, context, image_id):
        image_meta = {'disk_format': None,
                      'container_format': None}
        return image_meta

    def download(self, context, image_id, image_fd):
        for b in range(256):
            image_fd.write('some_image_data')
        image_fd.close()


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

        if not os.path.exists(self.volumes_path):
            os.mkdir(self.volumes_path)
        if not os.path.exists(self.images_dir):
            os.mkdir(self.images_dir)
        self.image_id = '70a599e0-31e7-49b7-b260-868f441e862b'

        self.driver = GPFSDriver(configuration=conf.Configuration(None))
        self.driver.set_execute(self._execute_wrapper)
        self.flags(volume_driver=self.driver_name,
                   gpfs_mount_point_base=self.volumes_path)
        self.volume = importutils.import_object(CONF.volume_manager)
        self.volume.driver.set_execute(self._execute_wrapper)
        self.volume.driver.set_initialized()

        self.stubs.Set(GPFSDriver, '_create_gpfs_snap',
                       self._fake_gpfs_snap)
        self.stubs.Set(GPFSDriver, '_create_gpfs_copy',
                       self._fake_gpfs_copy)
        self.stubs.Set(GPFSDriver, '_gpfs_redirect',
                       self._fake_gpfs_redirect)
        self.stubs.Set(GPFSDriver, '_is_gpfs_parent_file',
                       self._fake_is_gpfs_parent)
        self.stubs.Set(GPFSDriver, '_is_gpfs_path',
                       self._fake_is_gpfs_path)
        self.stubs.Set(GPFSDriver, '_delete_gpfs_file',
                       self._fake_delete_gpfs_file)
        self.stubs.Set(GPFSDriver, '_create_sparse_file',
                       self._fake_create_sparse_file)
        self.stubs.Set(GPFSDriver, '_allocate_file_blocks',
                       self._fake_allocate_file_blocks)
        self.stubs.Set(GPFSDriver, '_get_available_capacity',
                       self._fake_get_available_capacity)
        self.stubs.Set(image_utils, 'qemu_img_info',
                       self._fake_qemu_qcow2_image_info)
        self.stubs.Set(image_utils, 'convert_image',
                       self._fake_convert_image)
        self.stubs.Set(image_utils, 'resize_image',
                       self._fake_qemu_image_resize)

        self.context = context.get_admin_context()
        self.context.user_id = 'fake'
        self.context.project_id = 'fake'
        CONF.gpfs_images_dir = self.images_dir

    def tearDown(self):
        try:
            os.rmdir(self.images_dir)
            os.rmdir(self.volumes_path)
        except OSError:
            pass
        super(GPFSDriverTestCase, self).tearDown()

    def test_create_delete_volume_full_backing_file(self):
        """create and delete vol with full creation method"""
        CONF.gpfs_sparse_volumes = False
        vol = test_utils.create_volume(self.context, host=CONF.host)
        volume_id = vol['id']
        self.assertTrue(os.path.exists(self.volumes_path))
        self.volume.create_volume(self.context, volume_id)
        path = self.volumes_path + '/' + vol['name']
        self.assertTrue(os.path.exists(path))
        self.volume.delete_volume(self.context, volume_id)
        self.assertFalse(os.path.exists(path))

    def test_create_delete_volume_sparse_backing_file(self):
        """create and delete vol with default sparse creation method"""
        CONF.gpfs_sparse_volumes = True
        vol = test_utils.create_volume(self.context, host=CONF.host)
        volume_id = vol['id']
        self.assertTrue(os.path.exists(self.volumes_path))
        self.volume.create_volume(self.context, volume_id)
        path = self.volumes_path + '/' + vol['name']
        self.assertTrue(os.path.exists(path))
        self.volume.delete_volume(self.context, volume_id)
        self.assertFalse(os.path.exists(path))

    def test_create_volume_with_attributes(self):
        self.stubs.Set(GPFSDriver, '_gpfs_change_attributes',
                       self._fake_gpfs_change_attributes)
        attributes = {'dio': 'yes', 'data_pool_name': 'ssd_pool',
                      'replicas': '2', 'write_affinity_depth': '1',
                      'block_group_factor': '1',
                      'write_affinity_failure-group':
                      '1,1,1:2;2,1,1:2;2,0,3:4'}
        vol = test_utils.create_volume(self.context, host=CONF.host,
                                       metadata=attributes)
        volume_id = vol['id']
        self.assertTrue(os.path.exists(self.volumes_path))
        self.volume.create_volume(self.context, volume_id)
        path = self.volumes_path + '/' + vol['name']
        self.assertTrue(os.path.exists(path))
        self.volume.delete_volume(self.context, volume_id)
        self.assertFalse(os.path.exists(path))

    def test_migrate_volume(self):
        """Test volume migration done by driver."""
        loc = 'GPFSDriver:cindertest:openstack'
        cap = {'location_info': loc}
        host = {'host': 'foo', 'capabilities': cap}
        volume = test_utils.create_volume(self.context, host=CONF.host)
        self.driver.create_volume(volume)
        self.driver.migrate_volume(self.context, volume, host)
        self.driver.delete_volume(volume)

    def _create_snapshot(self, volume_id, size='0'):
        """Create a snapshot object."""
        snap = {}
        snap['volume_size'] = size
        snap['user_id'] = 'fake'
        snap['project_id'] = 'fake'
        snap['volume_id'] = volume_id
        snap['status'] = "creating"
        return db.snapshot_create(context.get_admin_context(), snap)

    def test_create_delete_snapshot(self):
        volume_src = test_utils.create_volume(self.context, host=CONF.host)
        self.volume.create_volume(self.context, volume_src['id'])
        snapCount = len(db.snapshot_get_all_for_volume(self.context,
                                                       volume_src['id']))
        self.assertEqual(snapCount, 0)
        snapshot = self._create_snapshot(volume_src['id'])
        snapshot_id = snapshot['id']
        self.volume.create_snapshot(self.context, volume_src['id'],
                                    snapshot_id)
        self.assertTrue(os.path.exists(os.path.join(self.volumes_path,
                                                    snapshot['name'])))
        snapCount = len(db.snapshot_get_all_for_volume(self.context,
                                                       volume_src['id']))
        self.assertEqual(snapCount, 1)
        self.volume.delete_snapshot(self.context, snapshot_id)
        self.volume.delete_volume(self.context, volume_src['id'])
        self.assertFalse(os.path.exists(os.path.join(self.volumes_path,
                                                     snapshot['name'])))
        snapCount = len(db.snapshot_get_all_for_volume(self.context,
                                                       volume_src['id']))
        self.assertEqual(snapCount, 0)

    def test_create_volume_from_snapshot(self):
        volume_src = test_utils.create_volume(self.context, host=CONF.host)
        self.volume.create_volume(self.context, volume_src['id'])
        snapshot = self._create_snapshot(volume_src['id'])
        snapshot_id = snapshot['id']
        self.volume.create_snapshot(self.context, volume_src['id'],
                                    snapshot_id)
        self.assertTrue(os.path.exists(os.path.join(self.volumes_path,
                                                    snapshot['name'])))
        volume_dst = test_utils.create_volume(self.context, host=CONF.host,
                                              snapshot_id=snapshot_id)
        self.volume.create_volume(self.context, volume_dst['id'], snapshot_id)
        self.assertEqual(volume_dst['id'], db.volume_get(
                         context.get_admin_context(),
                         volume_dst['id']).id)
        self.assertEqual(snapshot_id, db.volume_get(
                         context.get_admin_context(),
                         volume_dst['id']).snapshot_id)
        self.volume.delete_volume(self.context, volume_dst['id'])

        self.volume.delete_snapshot(self.context, snapshot_id)
        self.volume.delete_volume(self.context, volume_src['id'])

    def test_create_cloned_volume(self):
        volume_src = test_utils.create_volume(self.context, host=CONF.host)
        self.volume.create_volume(self.context, volume_src['id'])

        volume_dst = test_utils.create_volume(self.context, host=CONF.host)
        volumepath = os.path.join(self.volumes_path, volume_dst['name'])
        self.assertFalse(os.path.exists(volumepath))

        self.driver.create_cloned_volume(volume_dst, volume_src)
        self.assertEqual(volume_dst['id'], db.volume_get(
                         context.get_admin_context(),
                         volume_dst['id']).id)

        self.assertTrue(os.path.exists(volumepath))

        self.volume.delete_volume(self.context, volume_src['id'])
        self.volume.delete_volume(self.context, volume_dst['id'])

    def test_create_volume_from_snapshot_method(self):
        volume_src = test_utils.create_volume(self.context, host=CONF.host)
        self.volume.create_volume(self.context, volume_src['id'])

        snapshot = self._create_snapshot(volume_src['id'])
        snapshot_id = snapshot['id']
        self.volume.create_snapshot(self.context, volume_src['id'],
                                    snapshot_id)
        volume_dst = test_utils.create_volume(self.context, host=CONF.host)
        self.driver.create_volume_from_snapshot(volume_dst, snapshot)
        self.assertEqual(volume_dst['id'], db.volume_get(
                         context.get_admin_context(),
                         volume_dst['id']).id)

        volumepath = os.path.join(self.volumes_path, volume_dst['name'])
        self.assertTrue(os.path.exists(volumepath))

        self.volume.delete_snapshot(self.context, snapshot_id)
        self.volume.delete_volume(self.context, volume_dst['id'])
        self.volume.delete_volume(self.context, volume_src['id'])

    def test_clone_image_to_volume_with_copy_on_write_mode(self):
        """Test the function of copy_image_to_volume
        focusing on the integretion of the image_util
        using copy_on_write image sharing mode.
        """

        # specify image file format is raw
        self.stubs.Set(image_utils, 'qemu_img_info',
                       self._fake_qemu_raw_image_info)

        volume = test_utils.create_volume(self.context, host=CONF.host)
        volumepath = os.path.join(self.volumes_path, volume['name'])
        CONF.gpfs_images_share_mode = 'copy_on_write'
        self.driver.clone_image(volume,
                                None,
                                self.image_id)

        self.assertTrue(os.path.exists(volumepath))
        self.volume.delete_volume(self.context, volume['id'])
        self.assertFalse(os.path.exists(volumepath))

    def test_clone_image_to_volume_with_copy_mode(self):
        """Test the function of copy_image_to_volume
        focusing on the integretion of the image_util
        using copy image sharing mode.
        """

        # specify image file format is raw
        self.stubs.Set(image_utils, 'qemu_img_info',
                       self._fake_qemu_raw_image_info)

        volume = test_utils.create_volume(self.context, host=CONF.host)
        volumepath = os.path.join(self.volumes_path, volume['name'])
        CONF.gpfs_images_share_mode = 'copy'
        self.driver.clone_image(volume,
                                None,
                                self.image_id)

        self.assertTrue(os.path.exists(volumepath))
        self.volume.delete_volume(self.context, volume['id'])

    def test_copy_image_to_volume_with_non_gpfs_image_dir(self):
        """Test the function of copy_image_to_volume
        focusing on the integretion of the image_util
        using a non gpfs glance images directory
        """
        # specify image file format is raw
        self.stubs.Set(image_utils, 'qemu_img_info',
                       self._fake_qemu_raw_image_info)

        for share_mode in ['copy_on_write', 'copy']:
            volume = test_utils.create_volume(self.context, host=CONF.host)
            volumepath = os.path.join(self.volumes_path, volume['name'])
            CONF.gpfs_images_share_mode = share_mode
            CONF.gpfs_images_dir = None
            self.driver.copy_image_to_volume(self.context,
                                             volume,
                                             FakeImageService(),
                                             self.image_id)
            self.assertTrue(os.path.exists(volumepath))
            self.volume.delete_volume(self.context, volume['id'])

    def test_copy_image_to_volume_with_illegal_image_format(self):
        """Test the function of copy_image_to_volume
        focusing on the integretion of the image_util
        using an illegal image file format
        """
        # specify image file format is qcow2
        self.stubs.Set(image_utils, 'qemu_img_info',
                       self._fake_qemu_qcow2_image_info)

        volume = test_utils.create_volume(self.context, host=CONF.host)
        CONF.gpfs_images_share_mode = 'copy'
        CONF.gpfs_images_dir = self.images_dir
        self.assertRaises(exception.ImageUnacceptable,
                          self.driver.copy_image_to_volume,
                          self.context,
                          volume,
                          FakeImageService(),
                          self.image_id)

        self.volume.delete_volume(self.context, volume['id'])

    def test_get_volume_stats(self):
        stats = self.driver.get_volume_stats()
        self.assertEqual(stats['volume_backend_name'], 'GPFS')
        self.assertEqual(stats['storage_protocol'], 'file')

    def test_extend_volume(self):
        new_vol_size = 15
        mox = mox_lib.Mox()
        volume = test_utils.create_volume(self.context, host=CONF.host)
        volpath = os.path.join(self.volumes_path, volume['name'])

        qemu_img_info_output = """image: %s
        file format: raw
        virtual size: %sG (%s bytes)
        backing file: %s
        """ % (volume['name'], new_vol_size, new_vol_size * units.GiB, volpath)
        mox.StubOutWithMock(image_utils, 'resize_image')
        image_utils.resize_image(volpath, new_vol_size)

        mox.StubOutWithMock(image_utils, 'qemu_img_info')
        img_info = imageutils.QemuImgInfo(qemu_img_info_output)
        image_utils.qemu_img_info(volpath).AndReturn(img_info)
        mox.ReplayAll()

        self.driver.extend_volume(volume, new_vol_size)
        mox.VerifyAll()

    def test_extend_volume_with_failure(self):
        new_vol_size = 15
        mox = mox_lib.Mox()
        volume = test_utils.create_volume(self.context, host=CONF.host)
        volpath = os.path.join(self.volumes_path, volume['name'])

        mox.StubOutWithMock(image_utils, 'resize_image')
        image_utils.resize_image(volpath, new_vol_size).AndRaise(
            processutils.ProcessExecutionError('error'))
        mox.ReplayAll()

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.extend_volume, volume, new_vol_size)
        mox.VerifyAll()

    def test_check_for_setup_error_ok(self):
        self.stubs.Set(GPFSDriver, '_get_gpfs_state',
                       self._fake_gpfs_get_state_active)
        self.stubs.Set(GPFSDriver, '_get_gpfs_cluster_release_level',
                       self._fake_gpfs_compatible_cluster_release_level)
        self.stubs.Set(GPFSDriver, '_get_gpfs_filesystem_release_level',
                       self._fake_gpfs_compatible_filesystem_release_level)
        self.driver.check_for_setup_error()

    def test_check_for_setup_error_gpfs_not_active(self):
        self.stubs.Set(GPFSDriver, '_get_gpfs_state',
                       self._fake_gpfs_get_state_not_active)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.check_for_setup_error)

    def test_check_for_setup_error_not_gpfs_path(self):
        self.stubs.Set(GPFSDriver, '_get_gpfs_state',
                       self._fake_gpfs_get_state_active)
        self.stubs.Set(GPFSDriver, '_is_gpfs_path',
                       self._fake_is_not_gpfs_path)
        self.stubs.Set(GPFSDriver, '_get_gpfs_cluster_release_level',
                       self._fake_gpfs_compatible_cluster_release_level)
        self.stubs.Set(GPFSDriver, '_get_gpfs_filesystem_release_level',
                       self._fake_gpfs_compatible_filesystem_release_level)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.check_for_setup_error)

    def test_check_for_setup_error_incompatible_cluster_version(self):
        self.stubs.Set(GPFSDriver, '_get_gpfs_state',
                       self._fake_gpfs_get_state_active)
        self.stubs.Set(GPFSDriver, '_get_gpfs_cluster_release_level',
                       self._fake_gpfs_incompatible_cluster_release_level)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.check_for_setup_error)

    def test_check_for_setup_error_incompatible_filesystem_version(self):
        self.stubs.Set(GPFSDriver, '_get_gpfs_state',
                       self._fake_gpfs_get_state_active)
        self.stubs.Set(GPFSDriver, '_get_gpfs_cluster_release_level',
                       self._fake_gpfs_compatible_cluster_release_level)
        self.stubs.Set(GPFSDriver, '_get_gpfs_filesystem_release_level',
                       self._fake_gpfs_incompatible_filesystem_release_level)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.check_for_setup_error)

    def _fake_create_file(self, path, modebits='666'):
        open(path, 'w').close()
        utils.execute('chmod', modebits, path)

    def _fake_gpfs_snap(self, src, dest=None, modebits='644'):
        if dest is None:
            dest = src
        self._fake_create_file(dest, '644')

    def _fake_gpfs_copy(self, src, dest):
        self._fake_create_file(dest)

    def _fake_create_sparse_file(self, path, size):
        self._fake_create_file(path)

    def _fake_allocate_file_blocks(self, path, size):
        self._fake_create_file(path)

    def _fake_gpfs_change_attributes(self, options, path):
        pass

    def _fake_gpfs_redirect(self, src):
        return True

    def _fake_is_gpfs_parent(self, gpfs_file):
        return False

    def _fake_get_available_capacity(self, path):
        fake_avail = 80 * units.GiB
        fake_size = 2 * fake_avail
        return fake_avail, fake_size

    def _fake_gpfs_get_state_active(self):
        active_txt = ('mmgetstate::HEADER:version:reserved:reserved:'
                      'nodeName:nodeNumber:state:quorum:nodesUp:totalNodes:'
                      'remarks:cnfsState:\n'
                      'mmgetstate::0:1:::hostname:1:active:1:1:'
                      '1:quorum node:(undefined):')
        return active_txt

    def _fake_gpfs_get_state_not_active(self):
        inactive_txt = ('mmgetstate::HEADER:version:reserved:reserved:'
                        'nodeName:nodeNumber:state:quorum:nodesUp:totalNodes:'
                        'remarks:cnfsState:\n'
                        'mmgetstate::0:1:::hostname:1:down:1:1:'
                        '1:quorum node:(undefined):')
        return inactive_txt

    def _fake_gpfs_compatible_cluster_release_level(self):
        release = 1400
        return release

    def _fake_gpfs_incompatible_cluster_release_level(self):
        release = 1105
        return release

    def _fake_gpfs_compatible_filesystem_release_level(self, path=None):
        release = 1400
        fs = '/dev/gpfs'
        return fs, release

    def _fake_gpfs_incompatible_filesystem_release_level(self, path=None):
        release = 1105
        fs = '/dev/gpfs'
        return fs, release

    def _fake_is_gpfs_path(self, path):
        pass

    def _fake_is_not_gpfs_path(self, path):
        raise(processutils.ProcessExecutionError('invalid gpfs path'))

    def _fake_convert_image(self, source, dest, out_format):
        utils.execute('cp', source, dest)

    def _fake_qemu_qcow2_image_info(self, path):
        data = FakeQemuImgInfo()
        data.file_format = 'qcow2'
        data.backing_file = None
        data.virtual_size = 1 * units.GiB
        return data

    def _fake_qemu_raw_image_info(self, path):
        data = FakeQemuImgInfo()
        data.file_format = 'raw'
        data.backing_file = None
        data.virtual_size = 1 * units.GiB
        return data

    def _fake_qemu_image_resize(self, path, size):
        LOG.info('wtf')
        pass

    def _fake_delete_gpfs_file(self, fchild):
        volume_path = fchild
        vol_name = os.path.basename(fchild)
        vol_id = vol_name.split('volume-').pop()
        utils.execute('rm', '-f', volume_path)
        utils.execute('rm', '-f', volume_path + '.snap')
        all_snaps = db.snapshot_get_all_for_volume(self.context, vol_id)
        for snap in all_snaps:
            snap_path = self.volumes_path + '/' + snap['name']
            utils.execute('rm', '-f', snap_path)
