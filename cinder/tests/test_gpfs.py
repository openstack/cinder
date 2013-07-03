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

import os
import tempfile

from oslo.config import cfg

from cinder import context
from cinder import db
from cinder import exception
from cinder.image import image_utils
from cinder.openstack.common import importutils
from cinder.openstack.common import log as logging
from cinder import test
from cinder import utils
from cinder.volume import configuration as conf
from cinder.volume.drivers.gpfs import GPFSDriver

LOG = logging.getLogger(__name__)

CONF = cfg.CONF


class FakeImageService():
    def update(self, context, image_id, path):
        pass

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
        self.image_path = self.images_dir + "/" + self.image_id
        utils.execute('truncate', '-s', 1024, self.image_path)

        self.driver = GPFSDriver(configuration=conf.Configuration(None))
        self.driver.set_execute(self._execute_wrapper)
        self.flags(volume_driver=self.driver_name,
                   gpfs_mount_point_base=self.volumes_path)
        self.volume = importutils.import_object(CONF.volume_manager)
        self.volume.driver.set_execute(self._execute_wrapper)

        self.stubs.Set(GPFSDriver, '_create_gpfs_snap',
                       self._fake_gpfs_snap)
        self.stubs.Set(GPFSDriver, '_create_gpfs_copy',
                       self._fake_gpfs_copy)
        self.stubs.Set(GPFSDriver, '_gpfs_redirect',
                       self._fake_gpfs_redirect)
        self.stubs.Set(GPFSDriver, '_is_gpfs_parent_file',
                       self._fake_is_gpfs_parent)
        self.stubs.Set(GPFSDriver, '_delete_gpfs_file',
                       self._fake_delete_gpfs_file)
        self.stubs.Set(image_utils, 'qemu_img_info',
                       self._fake_qemu_qcow2_image_info)
        self.stubs.Set(image_utils, 'convert_image',
                       self._fake_convert_image)

        self.context = context.get_admin_context()

        CONF.gpfs_images_dir = self.images_dir

    def tearDown(self):
        try:
            os.remove(self.image_path)
            os.rmdir(self.images_dir)
            os.rmdir(self.volumes_path)
        except OSError:
            pass
        super(GPFSDriverTestCase, self).tearDown()

    def _create_volume(self, size=0, snapshot_id=None, image_id=None,
                       metadata=None):
        """Create a volume object."""
        vol = {}
        vol['size'] = size
        vol['snapshot_id'] = snapshot_id
        vol['image_id'] = image_id
        vol['user_id'] = 'fake'
        vol['project_id'] = 'fake'
        vol['availability_zone'] = CONF.storage_availability_zone
        vol['status'] = "creating"
        vol['attach_status'] = "detached"
        vol['host'] = CONF.host
        if metadata is not None:
            vol['metadata'] = metadata
        return db.volume_create(context.get_admin_context(), vol)

    def test_create_delete_volume_full_backing_file(self):
        """create and delete vol with full creation method"""
        CONF.gpfs_sparse_volumes = False
        vol = self._create_volume(size=1)
        volume_id = vol['id']
        self.assertTrue(os.path.exists(self.volumes_path))
        self.volume.create_volume(self.context, volume_id)
        path = self.volumes_path + '/' + vol['name']
        self.assertTrue(os.path.exists(self.volumes_path))
        self.assertTrue(os.path.exists(path))
        self.volume.delete_volume(self.context, volume_id)
        self.assertFalse(os.path.exists(path))
        self.assertTrue(os.path.exists(self.volumes_path))

    def test_create_delete_volume_sparse_backing_file(self):
        """create and delete vol with default sparse creation method"""
        CONF.gpfs_sparse_volumes = True
        vol = self._create_volume(size=1)
        volume_id = vol['id']
        self.assertTrue(os.path.exists(self.volumes_path))
        self.volume.create_volume(self.context, volume_id)
        path = self.volumes_path + '/' + vol['name']
        self.assertTrue(os.path.exists(self.volumes_path))
        self.assertTrue(os.path.exists(path))
        self.volume.delete_volume(self.context, volume_id)
        self.assertFalse(os.path.exists(path))
        self.assertTrue(os.path.exists(self.volumes_path))

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
        volume_src = self._create_volume()
        self.volume.create_volume(self.context, volume_src['id'])
        snapCount = len(db.snapshot_get_all_for_volume(self.context,
                                                       volume_src['id']))
        self.assertTrue(snapCount == 0)
        snapshot = self._create_snapshot(volume_src['id'])
        snapshot_id = snapshot['id']
        self.volume.create_snapshot(self.context, volume_src['id'],
                                    snapshot_id)
        self.assertTrue(os.path.exists(os.path.join(self.volumes_path,
                                                    snapshot['name'])))
        snapCount = len(db.snapshot_get_all_for_volume(self.context,
                                                       volume_src['id']))
        self.assertTrue(snapCount == 1)
        self.volume.delete_volume(self.context, volume_src['id'])
        self.volume.delete_snapshot(self.context, snapshot_id)
        self.assertFalse(os.path.exists(os.path.join(self.volumes_path,
                                                     snapshot['name'])))
        snapCount = len(db.snapshot_get_all_for_volume(self.context,
                                                       volume_src['id']))
        self.assertTrue(snapCount == 0)

    def test_create_volume_from_snapshot(self):
        volume_src = self._create_volume()
        self.volume.create_volume(self.context, volume_src['id'])
        snapshot = self._create_snapshot(volume_src['id'])
        snapshot_id = snapshot['id']
        self.volume.create_snapshot(self.context, volume_src['id'],
                                    snapshot_id)
        self.assertTrue(os.path.exists(os.path.join(self.volumes_path,
                                                    snapshot['name'])))
        volume_dst = self._create_volume(0, snapshot_id)
        self.volume.create_volume(self.context, volume_dst['id'], snapshot_id)
        self.assertEqual(volume_dst['id'], db.volume_get(
                         context.get_admin_context(),
                         volume_dst['id']).id)
        self.assertEqual(snapshot_id, db.volume_get(
                         context.get_admin_context(),
                         volume_dst['id']).snapshot_id)
        self.volume.delete_volume(self.context, volume_dst['id'])

        self.volume.delete_volume(self.context, volume_src['id'])
        self.volume.delete_snapshot(self.context, snapshot_id)

    def test_create_cloned_volume(self):
        volume_src = self._create_volume()
        self.volume.create_volume(self.context, volume_src['id'])

        volume_dst = self._create_volume()
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
        volume_src = self._create_volume()
        self.volume.create_volume(self.context, volume_src['id'])

        snapshot = self._create_snapshot(volume_src['id'])
        snapshot_id = snapshot['id']
        self.volume.create_snapshot(self.context, volume_src['id'],
                                    snapshot_id)
        volume_dst = self._create_volume()
        self.driver.create_volume_from_snapshot(volume_dst, snapshot)
        self.assertEqual(volume_dst['id'], db.volume_get(
                         context.get_admin_context(),
                         volume_dst['id']).id)

        volumepath = os.path.join(self.volumes_path, volume_dst['name'])
        self.assertTrue(os.path.exists(volumepath))

        self.volume.delete_volume(self.context, volume_dst['id'])
        self.volume.delete_volume(self.context, volume_src['id'])
        self.volume.delete_snapshot(self.context, snapshot_id)

    def test_copy_image_to_volume_with_copy_on_write_mode(self):
        """Test the function of copy_image_to_volume
        focusing on the integretion of the image_util
        using copy_on_write image sharing mode.
        """

        # specify image file format is raw
        self.stubs.Set(image_utils, 'qemu_img_info',
                       self._fake_qemu_raw_image_info)

        volume = self._create_volume()
        volumepath = os.path.join(self.volumes_path, volume['name'])
        CONF.gpfs_images_share_mode = 'copy_on_write'
        self.driver.copy_image_to_volume(self.context,
                                         volume,
                                         FakeImageService(),
                                         self.image_id)

        self.assertTrue(os.path.exists(volumepath))
        self.volume.delete_volume(self.context, volume['id'])
        self.assertFalse(os.path.exists(volumepath))

    def test_copy_image_to_volume_with_copy_mode(self):
        """Test the function of copy_image_to_volume
        focusing on the integretion of the image_util
        using copy image sharing mode.
        """

        # specify image file format is raw
        self.stubs.Set(image_utils, 'qemu_img_info',
                       self._fake_qemu_raw_image_info)

        volume = self._create_volume()
        volumepath = os.path.join(self.volumes_path, volume['name'])
        CONF.gpfs_images_share_mode = 'copy'
        self.driver.copy_image_to_volume(self.context,
                                         volume,
                                         FakeImageService(),
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
            volume = self._create_volume()
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

        volume = self._create_volume()
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
        self.assertEquals(stats['volume_backend_name'], 'GPFS')
        self.assertEquals(stats['storage_protocol'], 'file')

    def test_check_for_setup_error_ok(self):
        self.stubs.Set(GPFSDriver, '_get_gpfs_state',
                       self._fake_gpfs_get_state_active)
        self.stubs.Set(GPFSDriver, '_is_gpfs_path',
                       self._fake_is_gpfs_path)
        self.driver.check_for_setup_error()

    def test_check_for_setup_error_gpfs_not_active(self):
        self.stubs.Set(GPFSDriver, '_get_gpfs_state',
                       self._fake_gpfs_get_state_not_active)
        self.stubs.Set(GPFSDriver, '_is_gpfs_path',
                       self._fake_is_gpfs_path)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.check_for_setup_error)

    def test_check_for_setup_error_not_gpfs_path(self):
        self.stubs.Set(GPFSDriver, '_get_gpfs_state',
                       self._fake_gpfs_get_state_active)
        self.stubs.Set(GPFSDriver, '_is_gpfs_path',
                       self._fake_is_not_gpfs_path)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.check_for_setup_error)

    def _fake_gpfs_snap(self, src, dest=None, modebits='644'):
        if dest is None:
            dest = src
        utils.execute('truncate', '-s', 0, dest)
        utils.execute('chmod', '644', dest)

    def _fake_gpfs_copy(self, src, dest):
        utils.execute('truncate', '-s', 0, dest)
        utils.execute('chmod', '666', dest)

    def _fake_gpfs_redirect(self, src):
        return True

    def _fake_is_gpfs_parent(self, gpfs_file):
        return False

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

    def _fake_is_gpfs_path(self, path):
        pass

    def _fake_is_not_gpfs_path(self, path):
        raise(exception.ProcessExecutionError('invalid gpfs path'))

    def _fake_convert_image(self, source, dest, out_format):
        utils.execute('cp', source, dest)

    def _fake_qemu_qcow2_image_info(self, path):
        data = FakeQemuImgInfo()
        data.file_format = 'qcow2'
        data.backing_file = None
        data.virtual_size = 1024 * 1024 * 1024
        return data

    def _fake_qemu_raw_image_info(self, path):
        data = FakeQemuImgInfo()
        data.file_format = 'raw'
        data.backing_file = None
        data.virtual_size = 1024 * 1024 * 1024
        return data

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
