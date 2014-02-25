
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

import mock
import os
import tempfile

from oslo.config import cfg

from cinder import context
from cinder import db
from cinder import exception
from cinder.image import image_utils
from cinder.openstack.common import imageutils
from cinder.openstack.common import log as logging
from cinder.openstack.common import processutils
from cinder import test
from cinder.tests import utils as test_utils
from cinder import units
from cinder import utils
from cinder.volume import configuration as conf
from cinder.volume.drivers.ibm import gpfs
from cinder.volume import volume_types

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

        self.driver = gpfs.GPFSDriver(configuration=conf.Configuration(None))
        self.driver.set_execute(self._execute_wrapper)
        self.driver._cluster_id = '123456'
        self.driver._gpfs_device = '/dev/gpfs'
        self.driver._storage_pool = 'system'

        self.flags(volume_driver=self.driver_name,
                   gpfs_mount_point_base=self.volumes_path)

        self.stubs.Set(gpfs.GPFSDriver, '_create_gpfs_snap',
                       self._fake_gpfs_snap)
        self.stubs.Set(gpfs.GPFSDriver, '_create_gpfs_copy',
                       self._fake_gpfs_copy)
        self.stubs.Set(gpfs.GPFSDriver, '_gpfs_redirect',
                       self._fake_gpfs_redirect)
        self.stubs.Set(gpfs.GPFSDriver, '_is_gpfs_parent_file',
                       self._fake_is_gpfs_parent)
        self.stubs.Set(gpfs.GPFSDriver, '_is_gpfs_path',
                       self._fake_is_gpfs_path)
        self.stubs.Set(gpfs.GPFSDriver, '_delete_gpfs_file',
                       self._fake_delete_gpfs_file)
        self.stubs.Set(gpfs.GPFSDriver, '_create_sparse_file',
                       self._fake_create_sparse_file)
        self.stubs.Set(gpfs.GPFSDriver, '_allocate_file_blocks',
                       self._fake_allocate_file_blocks)
        self.stubs.Set(gpfs.GPFSDriver, '_get_available_capacity',
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
        """Create and delete vol with full creation method."""
        CONF.gpfs_sparse_volumes = False
        vol = test_utils.create_volume(self.context, host=CONF.host)
        volume_id = vol['id']
        self.assertTrue(os.path.exists(self.volumes_path))
        self.driver.create_volume(vol)
        path = self.volumes_path + '/' + vol['name']
        self.assertTrue(os.path.exists(path))
        self.driver.delete_volume(vol)
        self.assertFalse(os.path.exists(path))

    def test_create_delete_volume_sparse_backing_file(self):
        """Create and delete vol with default sparse creation method."""
        CONF.gpfs_sparse_volumes = True
        vol = test_utils.create_volume(self.context, host=CONF.host)
        self.assertTrue(os.path.exists(self.volumes_path))
        self.driver.create_volume(vol)
        path = self.volumes_path + '/' + vol['name']
        self.assertTrue(os.path.exists(path))
        self.driver.delete_volume(vol)
        self.assertFalse(os.path.exists(path))

    def test_create_volume_with_attributes(self):
        self.stubs.Set(gpfs.GPFSDriver, '_gpfs_change_attributes',
                       self._fake_gpfs_change_attributes)
        attributes = {'dio': 'yes', 'data_pool_name': 'ssd_pool',
                      'replicas': '2', 'write_affinity_depth': '1',
                      'block_group_factor': '1',
                      'write_affinity_failure-group':
                      '1,1,1:2;2,1,1:2;2,0,3:4'}
        vol = test_utils.create_volume(self.context, host=CONF.host,
                                       metadata=attributes)
        self.assertTrue(os.path.exists(self.volumes_path))
        self.driver.create_volume(vol)
        path = self.volumes_path + '/' + vol['name']
        self.assertTrue(os.path.exists(path))
        self.driver.delete_volume(vol)
        self.assertFalse(os.path.exists(path))

    def test_migrate_volume_local(self):
        """Verify volume migration performed locally by driver."""
        ctxt = self.context
        migrated_by_driver = True
        volume = test_utils.create_volume(ctxt, host=CONF.host)
        with mock.patch('cinder.utils.execute'):
            LOG.debug('Migrate same cluster, different path, '
                      'move file to new path.')
            loc = 'GPFSDriver:%s:testpath' % self.driver._cluster_id
            cap = {'location_info': loc}
            host = {'host': 'foo', 'capabilities': cap}
            self.driver.create_volume(volume)
            migr, updt = self.driver.migrate_volume(ctxt, volume, host)
            self.assertEqual(migr, migrated_by_driver)
            self.driver.delete_volume(volume)
            LOG.debug('Migrate same cluster, different path, '
                      'move file to new path, rv = %s.' % migr)

            LOG.debug('Migrate same cluster, same path, no action taken.')
            gpfs_base = self.driver.configuration.gpfs_mount_point_base
            loc = 'GPFSDriver:%s:%s' % (self.driver._cluster_id, gpfs_base)
            cap = {'location_info': loc}
            host = {'host': 'foo', 'capabilities': cap}
            self.driver.create_volume(volume)
            migr, updt = self.driver.migrate_volume(ctxt, volume, host)
            self.assertEqual(migr, migrated_by_driver)
            self.driver.delete_volume(volume)
            LOG.debug('Migrate same cluster, same path, no action taken, '
                      'rv = %s' % migr)

    def test_migrate_volume_generic(self):
        """Verify cases where driver cannot perform migration locally."""
        ctxt = self.context
        migrated_by_driver = False
        volume = test_utils.create_volume(ctxt, host=CONF.host)
        with mock.patch('cinder.utils.execute'):
            LOG.debug('Migrate request for different cluster, return false '
                      'for generic migration.')
            other_cluster_id = '000000'
            loc = 'GPFSDriver:%s:testpath' % other_cluster_id
            cap = {'location_info': loc}
            host = {'host': 'foo', 'capabilities': cap}
            self.driver.create_volume(volume)
            migr, updt = self.driver.migrate_volume(ctxt, volume, host)
            self.assertEqual(migr, migrated_by_driver)
            self.driver.delete_volume(volume)
            LOG.debug('Migrate request for different cluster, rv = %s.' % migr)

            LOG.debug('Migrate request with no location info, return false '
                      'for generic migration.')
            host = {'host': 'foo', 'capabilities': {}}
            self.driver.create_volume(volume)
            migr, updt = self.driver.migrate_volume(ctxt, volume, host)
            self.assertEqual(migr, migrated_by_driver)
            self.driver.delete_volume(volume)
            LOG.debug('Migrate request with no location info, rv = %s.' % migr)

            LOG.debug('Migrate request with bad location info, return false '
                      'for generic migration.')
            bad_loc = 'GPFSDriver:testpath'
            cap = {'location_info': bad_loc}
            host = {'host': 'foo', 'capabilities': cap}
            self.driver.create_volume(volume)
            migr, updt = self.driver.migrate_volume(ctxt, volume, host)
            self.assertEqual(migr, migrated_by_driver)
            self.driver.delete_volume(volume)
            LOG.debug('Migrate request with bad location info, rv = %s.' %
                      migr)

    def test_retype_volume_different_pool(self):
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

        old_type = volume_types.get_volume_type(ctxt, old_type_ref['id'])
        new_type = volume_types.get_volume_type(ctxt, new_type_ref['id'])

        diff, equal = volume_types.volume_types_diff(ctxt,
                                                     old_type_ref['id'],
                                                     new_type_ref['id'])

        # set volume host to match target host
        volume = test_utils.create_volume(ctxt, host=host['host'])
        volume['volume_type_id'] = old_type['id']
        with mock.patch('cinder.utils.execute'):
            LOG.debug('Retype different pools, expected rv = True.')
            self.driver.create_volume(volume)
            rv = self.driver.retype(ctxt, volume, new_type, diff, host)
            self.assertTrue(rv)
            self.driver.delete_volume(volume)
            LOG.debug('Retype different pools, rv = %s.' % rv)

    def test_retype_volume_different_host(self):
        ctxt = self.context
        loc = 'GPFSDriver:%s:testpath' % self.driver._cluster_id
        cap = {'location_info': loc}
        host = {'host': 'foo', 'capabilities': cap}

        newloc = 'GPFSDriver:000000:testpath'
        newcap = {'location_info': newloc}
        newhost = {'host': 'foo', 'capabilities': newcap}

        key_specs_old = {'capabilities:storage_pool': 'bronze',
                         'volume_backend_name': 'backend1'}
        old_type_ref = volume_types.create(ctxt, 'old', key_specs_old)
        old_type = volume_types.get_volume_type(ctxt, old_type_ref['id'])
        diff, equal = volume_types.volume_types_diff(ctxt,
                                                     old_type_ref['id'],
                                                     old_type_ref['id'])
        # set volume host to be different from target host
        volume = test_utils.create_volume(ctxt, host=CONF.host)
        volume['volume_type_id'] = old_type['id']

        with mock.patch('cinder.utils.execute'):
            LOG.debug('Retype different hosts same cluster, '
                      'expected rv = True.')
            self.driver.db = mock.Mock()
            self.driver.create_volume(volume)
            rv = self.driver.retype(ctxt, volume, old_type, diff, host)
            self.assertTrue(rv)
            self.driver.delete_volume(volume)
            LOG.debug('Retype different hosts same cluster, rv = %s.' % rv)

            LOG.debug('Retype different hosts, different cluster, '
                      'cannot migrate.  Expected rv = False.')
            self.driver.create_volume(volume)
            rv = self.driver.retype(ctxt, volume, old_type, diff, newhost)
            self.assertFalse(rv)
            self.driver.delete_volume(volume)
            LOG.debug('Retype different hosts, different cluster, '
                      'cannot migrate, rv = %s.' % rv)

    def test_retype_volume_different_pool_and_host(self):
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

        old_type = volume_types.get_volume_type(ctxt, old_type_ref['id'])
        new_type = volume_types.get_volume_type(ctxt, new_type_ref['id'])

        diff, equal = volume_types.volume_types_diff(ctxt,
                                                     old_type_ref['id'],
                                                     new_type_ref['id'])

        # set volume host to be different from target host
        volume = test_utils.create_volume(ctxt, host=CONF.host)
        volume['volume_type_id'] = old_type['id']

        with mock.patch('cinder.utils.execute'):
            # different host different pool
            LOG.debug('Retype different pools and hosts, expected rv = True.')
            self.driver.db = mock.Mock()
            self.driver.create_volume(volume)
            rv = self.driver.retype(ctxt, volume, new_type, diff, host)
            self.assertTrue(rv)
            self.driver.delete_volume(volume)
            LOG.debug('Retype different pools and hosts, rv = %s.' % rv)

    def test_retype_volume_different_backend(self):
        ctxt = self.context
        loc = 'GPFSDriver:%s:testpath' % self.driver._cluster_id
        cap = {'location_info': loc}
        host = {'host': 'foo', 'capabilities': cap}

        key_specs_old = {'capabilities:storage_pool': 'bronze',
                         'volume_backend_name': 'backend1'}
        key_specs_new = {'capabilities:storage_pool': 'gold',
                         'volume_backend_name': 'backend2'}

        old_type_ref = volume_types.create(ctxt, 'old', key_specs_old)
        new_type_ref = volume_types.create(ctxt, 'new', key_specs_new)

        old_type = volume_types.get_volume_type(ctxt, old_type_ref['id'])
        new_type = volume_types.get_volume_type(ctxt, new_type_ref['id'])

        diff, equal = volume_types.volume_types_diff(ctxt,
                                                     old_type_ref['id'],
                                                     new_type_ref['id'])
        # set volume host to match target host
        volume = test_utils.create_volume(ctxt, host=host['host'])
        volume['volume_type_id'] = old_type['id']

        with mock.patch('cinder.utils.execute'):
            LOG.debug('Retype different backends, cannot migrate. '
                      'Expected rv = False.')
            self.driver.create_volume(volume)
            rv = self.driver.retype(ctxt, volume, old_type, diff, host)
            self.assertFalse(rv)
            self.driver.delete_volume(volume)
            LOG.debug('Retype different backends, cannot migrate, '
                      'rv = %s.' % rv)

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
        self.driver.create_volume(volume_src)
        snapCount = len(db.snapshot_get_all_for_volume(self.context,
                                                       volume_src['id']))
        snapshot = self._create_snapshot(volume_src['id'])
        self.driver.create_snapshot(snapshot)
        self.assertTrue(os.path.exists(os.path.join(self.volumes_path,
                                                    snapshot['name'])))
        self.driver.delete_snapshot(snapshot)
        self.driver.delete_volume(volume_src)
        self.assertFalse(os.path.exists(os.path.join(self.volumes_path,
                                                     snapshot['name'])))

    def test_create_volume_from_snapshot(self):
        volume_src = test_utils.create_volume(self.context, host=CONF.host)
        self.driver.create_volume(volume_src)
        snapshot = self._create_snapshot(volume_src['id'])
        snapshot_id = snapshot['id']
        self.driver.create_snapshot(snapshot)
        self.assertTrue(os.path.exists(os.path.join(self.volumes_path,
                                                    snapshot['name'])))
        volume_dst = test_utils.create_volume(self.context, host=CONF.host,
                                              snapshot_id=snapshot_id)
        self.driver.create_volume_from_snapshot(volume_dst, snapshot)
        self.assertEqual(volume_dst['id'], db.volume_get(
                         context.get_admin_context(),
                         volume_dst['id']).id)
        self.assertEqual(snapshot_id, db.volume_get(
                         context.get_admin_context(),
                         volume_dst['id']).snapshot_id)
        self.driver.delete_volume(volume_dst)

        self.driver.delete_snapshot(snapshot)
        self.driver.delete_volume(volume_src)

    def test_create_cloned_volume(self):
        volume_src = test_utils.create_volume(self.context, host=CONF.host)
        self.driver.create_volume(volume_src)

        volume_dst = test_utils.create_volume(self.context, host=CONF.host)
        volumepath = os.path.join(self.volumes_path, volume_dst['name'])
        self.assertFalse(os.path.exists(volumepath))

        self.driver.create_cloned_volume(volume_dst, volume_src)
        self.assertEqual(volume_dst['id'], db.volume_get(
                         context.get_admin_context(),
                         volume_dst['id']).id)

        self.assertTrue(os.path.exists(volumepath))
        self.driver.delete_volume(volume_src)
        self.driver.delete_volume(volume_dst)

    def test_create_volume_from_snapshot_method(self):
        volume_src = test_utils.create_volume(self.context, host=CONF.host)
        snapshot = self._create_snapshot(volume_src['id'])
        snapshot_id = snapshot['id']
        volume_dst = test_utils.create_volume(self.context, host=CONF.host)
        self.driver.create_volume_from_snapshot(volume_dst, snapshot)
        self.assertEqual(volume_dst['id'], db.volume_get(
                         context.get_admin_context(),
                         volume_dst['id']).id)

        volumepath = os.path.join(self.volumes_path, volume_dst['name'])
        self.assertTrue(os.path.exists(volumepath))
        self.driver.delete_volume(volume_dst)

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
                                self.image_id,
                                {})

        self.assertTrue(os.path.exists(volumepath))
        self.driver.delete_volume(volume)
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
                                self.image_id,
                                {})

        self.assertTrue(os.path.exists(volumepath))

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

    def test_get_volume_stats(self):
        stats = self.driver.get_volume_stats()
        self.assertEqual(stats['volume_backend_name'], 'GPFS')
        self.assertEqual(stats['storage_protocol'], 'file')

    def test_extend_volume(self):
        new_vol_size = 15
        volume = test_utils.create_volume(self.context, host=CONF.host)
        with mock.patch('cinder.image.image_utils.resize_image'):
            with mock.patch('cinder.image.image_utils.qemu_img_info'):
                self.driver.extend_volume(volume, new_vol_size)

    def test_extend_volume_with_failure(self):
        new_vol_size = 15
        volume = test_utils.create_volume(self.context, host=CONF.host)
        volpath = os.path.join(self.volumes_path, volume['name'])

        with mock.patch('cinder.image.image_utils.resize_image') as resize:
            with mock.patch('cinder.image.image_utils.qemu_img_info'):
                resize.side_effect = processutils.ProcessExecutionError('err')
                self.assertRaises(exception.VolumeBackendAPIException,
                                  self.driver.extend_volume,
                                  volume,
                                  new_vol_size)

    def test_resize_volume(self):
        new_vol_size = 15
        new_vol_size_bytes = new_vol_size * units.GiB
        volume = test_utils.create_volume(self.context, host=CONF.host)
        volpath = os.path.join(self.volumes_path, volume['name'])

        qemu_img_info_output = """image: %s
        file format: raw
        virtual size: %sG (%s bytes)
        backing file: %s
        """ % (volume['name'], new_vol_size, new_vol_size_bytes, volpath)
        img_info = imageutils.QemuImgInfo(qemu_img_info_output)

        with mock.patch('cinder.image.image_utils.resize_image'):
            with mock.patch('cinder.image.image_utils.qemu_img_info') as info:
                info.return_value = img_info
                rv = self.driver._resize_volume_file(volume, new_vol_size)
                self.assertEqual(rv, new_vol_size_bytes)

    def test_check_for_setup_error_ok(self):
        self.stubs.Set(gpfs.GPFSDriver, '_get_gpfs_state',
                       self._fake_gpfs_get_state_active)
        self.stubs.Set(gpfs.GPFSDriver, '_get_gpfs_cluster_release_level',
                       self._fake_gpfs_compatible_cluster_release_level)
        self.stubs.Set(gpfs.GPFSDriver, '_get_gpfs_fs_release_level',
                       self._fake_gpfs_compatible_filesystem_release_level)
        self.driver.check_for_setup_error()

    def test_check_for_setup_error_gpfs_not_active(self):
        self.stubs.Set(gpfs.GPFSDriver, '_get_gpfs_state',
                       self._fake_gpfs_get_state_not_active)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.check_for_setup_error)

    def test_check_for_setup_error_not_gpfs_path(self):
        self.stubs.Set(gpfs.GPFSDriver, '_get_gpfs_state',
                       self._fake_gpfs_get_state_active)
        self.stubs.Set(gpfs.GPFSDriver, '_is_gpfs_path',
                       self._fake_is_not_gpfs_path)
        self.stubs.Set(gpfs.GPFSDriver, '_get_gpfs_cluster_release_level',
                       self._fake_gpfs_compatible_cluster_release_level)
        self.stubs.Set(gpfs.GPFSDriver, '_get_gpfs_fs_release_level',
                       self._fake_gpfs_compatible_filesystem_release_level)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.check_for_setup_error)

    def test_check_for_setup_error_incompatible_cluster_version(self):
        self.stubs.Set(gpfs.GPFSDriver, '_get_gpfs_state',
                       self._fake_gpfs_get_state_active)
        self.stubs.Set(gpfs.GPFSDriver, '_get_gpfs_cluster_release_level',
                       self._fake_gpfs_incompatible_cluster_release_level)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.check_for_setup_error)

    def test_check_for_setup_error_incompatible_filesystem_version(self):
        self.stubs.Set(gpfs.GPFSDriver, '_get_gpfs_state',
                       self._fake_gpfs_get_state_active)
        self.stubs.Set(gpfs.GPFSDriver, '_get_gpfs_cluster_release_level',
                       self._fake_gpfs_compatible_cluster_release_level)
        self.stubs.Set(gpfs.GPFSDriver, '_get_gpfs_fs_release_level',
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

    def _fake_qemu_image_resize(self, path, size, run_as_root=False):
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
