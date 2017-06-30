#  Copyright 2014 Cloudbase Solutions Srl
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

import collections
import copy
import os

import ddt
import mock

from cinder import context
from cinder import exception
from cinder.image import image_utils
from cinder import test
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder import utils
from cinder.volume.drivers import remotefs


@ddt.ddt
class RemoteFsSnapDriverTestCase(test.TestCase):

    _FAKE_MNT_POINT = '/mnt/fake_hash'

    def setUp(self):
        super(RemoteFsSnapDriverTestCase, self).setUp()
        self._driver = remotefs.RemoteFSSnapDriver()
        self._driver._remotefsclient = mock.Mock()
        self._driver._execute = mock.Mock()
        self._driver._delete = mock.Mock()

        self.context = context.get_admin_context()

        self._fake_volume = fake_volume.fake_volume_obj(
            self.context, provider_location='fake_share')
        self._fake_volume_path = os.path.join(self._FAKE_MNT_POINT,
                                              self._fake_volume.name)
        self._fake_snapshot = fake_snapshot.fake_snapshot_obj(self.context)
        self._fake_snapshot_path = (self._fake_volume_path + '.' +
                                    self._fake_snapshot.id)
        self._fake_snapshot.volume = self._fake_volume

    @ddt.data({'current_state': 'in-use',
               'acceptable_states': ['available', 'in-use']},
              {'current_state': 'in-use',
               'acceptable_states': ['available'],
               'expected_exception': exception.InvalidVolume})
    @ddt.unpack
    def test_validate_state(self, current_state, acceptable_states,
                            expected_exception=None):
        if expected_exception:
            self.assertRaises(expected_exception,
                              self._driver._validate_state,
                              current_state,
                              acceptable_states)
        else:
            self._driver._validate_state(current_state, acceptable_states)

    def _test_delete_snapshot(self, volume_in_use=False,
                              stale_snapshot=False,
                              is_active_image=True,
                              is_tmp_snap=False):
        # If the snapshot is not the active image, it is guaranteed that
        # another snapshot exists having it as backing file.

        fake_snapshot_name = os.path.basename(self._fake_snapshot_path)
        fake_info = {'active': fake_snapshot_name,
                     self._fake_snapshot.id: fake_snapshot_name}
        fake_snap_img_info = mock.Mock()
        fake_base_img_info = mock.Mock()
        if stale_snapshot:
            fake_snap_img_info.backing_file = None
        else:
            fake_snap_img_info.backing_file = self._fake_volume.name
        fake_snap_img_info.file_format = 'qcow2'
        fake_base_img_info.backing_file = None
        fake_base_img_info.file_format = 'raw'

        self._driver._local_path_volume_info = mock.Mock(
            return_value=mock.sentinel.fake_info_path)
        self._driver._qemu_img_info = mock.Mock(
            side_effect=[fake_snap_img_info, fake_base_img_info])
        self._driver._local_volume_dir = mock.Mock(
            return_value=self._FAKE_MNT_POINT)

        self._driver._validate_state = mock.Mock()
        self._driver._read_info_file = mock.Mock()
        self._driver._write_info_file = mock.Mock()
        self._driver._img_commit = mock.Mock()
        self._driver._rebase_img = mock.Mock()
        self._driver._ensure_share_writable = mock.Mock()
        self._driver._delete_stale_snapshot = mock.Mock()
        self._driver._delete_snapshot_online = mock.Mock()

        expected_info = {
            'active': fake_snapshot_name,
            self._fake_snapshot.id: fake_snapshot_name
        }

        exp_acceptable_states = ['available', 'in-use', 'backing-up',
                                 'deleting', 'downloading']

        if volume_in_use:
            self._fake_snapshot.volume.status = 'in-use'

            self._driver._read_info_file.return_value = fake_info

            self._driver._delete_snapshot(self._fake_snapshot)
            self._driver._validate_state.assert_called_once_with(
                self._fake_snapshot.volume.status,
                exp_acceptable_states)
            if stale_snapshot:
                self._driver._delete_stale_snapshot.assert_called_once_with(
                    self._fake_snapshot)
            else:
                expected_online_delete_info = {
                    'active_file': fake_snapshot_name,
                    'snapshot_file': fake_snapshot_name,
                    'base_file': self._fake_volume.name,
                    'base_id': None,
                    'new_base_file': None
                }
                self._driver._delete_snapshot_online.assert_called_once_with(
                    self.context, self._fake_snapshot,
                    expected_online_delete_info)

        elif is_active_image:
            self._driver._read_info_file.return_value = fake_info

            self._driver._delete_snapshot(self._fake_snapshot)

            self._driver._img_commit.assert_called_once_with(
                self._fake_snapshot_path)
            self.assertNotIn(self._fake_snapshot.id, fake_info)
            self._driver._write_info_file.assert_called_once_with(
                mock.sentinel.fake_info_path, fake_info)
        else:
            fake_upper_snap_id = 'fake_upper_snap_id'
            fake_upper_snap_path = (
                self._fake_volume_path + '-snapshot' + fake_upper_snap_id)
            fake_upper_snap_name = os.path.basename(fake_upper_snap_path)

            fake_backing_chain = [
                {'filename': fake_upper_snap_name,
                 'backing-filename': fake_snapshot_name},
                {'filename': fake_snapshot_name,
                 'backing-filename': self._fake_volume.name},
                {'filename': self._fake_volume.name,
                 'backing-filename': None}]

            fake_info[fake_upper_snap_id] = fake_upper_snap_name
            fake_info[self._fake_snapshot.id] = fake_snapshot_name
            fake_info['active'] = fake_upper_snap_name

            expected_info = copy.deepcopy(fake_info)
            del expected_info[self._fake_snapshot.id]

            self._driver._read_info_file.return_value = fake_info
            self._driver._get_backing_chain_for_path = mock.Mock(
                return_value=fake_backing_chain)

            self._driver._delete_snapshot(self._fake_snapshot)

            self._driver._img_commit.assert_called_once_with(
                self._fake_snapshot_path)
            self._driver._rebase_img.assert_called_once_with(
                fake_upper_snap_path, self._fake_volume.name,
                fake_base_img_info.file_format)
            self._driver._write_info_file.assert_called_once_with(
                mock.sentinel.fake_info_path, expected_info)

    def test_delete_snapshot_when_active_file(self):
        self._test_delete_snapshot()

    def test_delete_snapshot_in_use(self):
        self._test_delete_snapshot(volume_in_use=True)

    def test_delete_snapshot_in_use_stale_snapshot(self):
        self._test_delete_snapshot(volume_in_use=True,
                                   stale_snapshot=True)

    def test_delete_snapshot_with_one_upper_file(self):
        self._test_delete_snapshot(is_active_image=False)

    def test_delete_stale_snapshot(self):
        fake_snapshot_name = os.path.basename(self._fake_snapshot_path)
        fake_snap_info = {
            'active': self._fake_volume.name,
            self._fake_snapshot.id: fake_snapshot_name
        }
        expected_info = {'active': self._fake_volume.name}

        self._driver._local_path_volume_info = mock.Mock(
            return_value=mock.sentinel.fake_info_path)
        self._driver._read_info_file = mock.Mock(
            return_value=fake_snap_info)
        self._driver._local_volume_dir = mock.Mock(
            return_value=self._FAKE_MNT_POINT)
        self._driver._write_info_file = mock.Mock()

        self._driver._delete_stale_snapshot(self._fake_snapshot)

        self._driver._delete.assert_called_once_with(self._fake_snapshot_path)
        self._driver._write_info_file.assert_called_once_with(
            mock.sentinel.fake_info_path, expected_info)

    @mock.patch.object(remotefs.RemoteFSDriver,
                       'secure_file_operations_enabled',
                       return_value=True)
    @mock.patch.object(os, 'stat')
    def test_do_create_snapshot(self, _mock_stat, _mock_sec_enabled):
        self._driver._local_volume_dir = mock.Mock(
            return_value=self._fake_volume_path)
        fake_backing_path = os.path.join(
            self._driver._local_volume_dir(),
            self._fake_volume.name)

        self._driver._execute = mock.Mock()
        self._driver._set_rw_permissions = mock.Mock()
        self._driver._qemu_img_info = mock.Mock(
            return_value=mock.Mock(file_format=mock.sentinel.backing_fmt))

        self._driver._do_create_snapshot(self._fake_snapshot,
                                         self._fake_volume.name,
                                         self._fake_snapshot_path)
        command1 = ['qemu-img', 'create', '-f', 'qcow2', '-o',
                    'backing_file=%s,backing_fmt=%s' %
                    (fake_backing_path,
                     mock.sentinel.backing_fmt),
                    self._fake_snapshot_path,
                    "%dG" % self._fake_volume.size]
        command2 = ['qemu-img', 'rebase', '-u',
                    '-b', self._fake_volume.name,
                    '-F', mock.sentinel.backing_fmt,
                    self._fake_snapshot_path]
        command3 = ['chown', '--reference=%s' % fake_backing_path,
                    self._fake_snapshot_path]
        calls = [mock.call(*command1, run_as_root=True),
                 mock.call(*command2, run_as_root=True),
                 mock.call(*command3, run_as_root=True)]
        self._driver._execute.assert_has_calls(calls)

    def _test_create_snapshot(self, volume_in_use=False, tmp_snap=False):
        fake_snapshot_info = {}
        fake_snapshot_file_name = os.path.basename(self._fake_snapshot_path)

        self._driver._local_path_volume_info = mock.Mock(
            return_value=mock.sentinel.fake_info_path)
        self._driver._read_info_file = mock.Mock(
            return_value=fake_snapshot_info)
        self._driver._do_create_snapshot = mock.Mock()
        self._driver._create_snapshot_online = mock.Mock()
        self._driver._write_info_file = mock.Mock()
        self._driver.get_active_image_from_info = mock.Mock(
            return_value=self._fake_volume.name)
        self._driver._get_new_snap_path = mock.Mock(
            return_value=self._fake_snapshot_path)
        self._driver._validate_state = mock.Mock()

        expected_snapshot_info = {
            'active': fake_snapshot_file_name,
            self._fake_snapshot.id: fake_snapshot_file_name
        }
        exp_acceptable_states = ['available', 'in-use', 'backing-up']
        if tmp_snap:
            exp_acceptable_states.append('downloading')
            self._fake_snapshot.id = 'tmp-snap-%s' % self._fake_snapshot.id

        if volume_in_use:
            self._fake_snapshot.volume.status = 'in-use'
            expected_method_called = '_create_snapshot_online'
        else:
            self._fake_snapshot.volume.status = 'available'
            expected_method_called = '_do_create_snapshot'

        self._driver._create_snapshot(self._fake_snapshot)

        self._driver._validate_state.assert_called_once_with(
            self._fake_snapshot.volume.status,
            exp_acceptable_states)
        fake_method = getattr(self._driver, expected_method_called)
        fake_method.assert_called_with(
            self._fake_snapshot, self._fake_volume.name,
            self._fake_snapshot_path)
        self._driver._write_info_file.assert_called_with(
            mock.sentinel.fake_info_path,
            expected_snapshot_info)

    def test_create_snapshot_volume_available(self):
        self._test_create_snapshot()

    def test_create_snapshot_volume_in_use(self):
        self._test_create_snapshot(volume_in_use=True)

    def test_create_snapshot_invalid_volume(self):
        self._fake_snapshot.volume.status = 'error'
        self.assertRaises(exception.InvalidVolume,
                          self._driver._create_snapshot,
                          self._fake_snapshot)

    @mock.patch('cinder.db.snapshot_get')
    @mock.patch('time.sleep')
    def test_create_snapshot_online_with_concurrent_delete(
            self, mock_sleep, mock_snapshot_get):
        self._driver._nova = mock.Mock()

        # Test what happens when progress is so slow that someone
        # decides to delete the snapshot while the last known status is
        # "creating".
        mock_snapshot_get.side_effect = [
            {'status': 'creating', 'progress': '42%'},
            {'status': 'creating', 'progress': '45%'},
            {'status': 'deleting'},
        ]

        with mock.patch.object(self._driver, '_do_create_snapshot') as \
                mock_do_create_snapshot:
            self.assertRaises(exception.RemoteFSConcurrentRequest,
                              self._driver._create_snapshot_online,
                              self._fake_snapshot,
                              self._fake_volume.name,
                              self._fake_snapshot_path)

        mock_do_create_snapshot.assert_called_once_with(
            self._fake_snapshot, self._fake_volume.name,
            self._fake_snapshot_path)
        self.assertEqual([mock.call(1), mock.call(1)],
                         mock_sleep.call_args_list)
        self.assertEqual(3, mock_snapshot_get.call_count)
        mock_snapshot_get.assert_called_with(self._fake_snapshot._context,
                                             self._fake_snapshot.id)

    @mock.patch.object(utils, 'synchronized')
    def _locked_volume_operation_test_helper(self, mock_synchronized, func,
                                             expected_exception=False,
                                             *args, **kwargs):
        def mock_decorator(*args, **kwargs):
            def mock_inner(f):
                return f
            return mock_inner

        mock_synchronized.side_effect = mock_decorator
        expected_lock = '%s-%s' % (self._driver.driver_prefix,
                                   self._fake_volume.id)

        if expected_exception:
            self.assertRaises(expected_exception, func,
                              self._driver,
                              *args, **kwargs)
        else:
            ret_val = func(self._driver, *args, **kwargs)

            mock_synchronized.assert_called_with(expected_lock,
                                                 external=False)
            self.assertEqual(mock.sentinel.ret_val, ret_val)

    def test_locked_volume_id_operation(self):
        mock_volume = mock.Mock()
        mock_volume.id = self._fake_volume.id

        @remotefs.locked_volume_id_operation
        def synchronized_func(inst, volume):
            return mock.sentinel.ret_val

        self._locked_volume_operation_test_helper(func=synchronized_func,
                                                  volume=mock_volume)

    def test_locked_volume_id_snapshot_operation(self):
        mock_snapshot = mock.Mock()
        mock_snapshot.volume.id = self._fake_volume.id

        @remotefs.locked_volume_id_operation
        def synchronized_func(inst, snapshot):
            return mock.sentinel.ret_val

        self._locked_volume_operation_test_helper(func=synchronized_func,
                                                  snapshot=mock_snapshot)

    def test_locked_volume_id_operation_exception(self):
        @remotefs.locked_volume_id_operation
        def synchronized_func(inst):
            return mock.sentinel.ret_val

        self._locked_volume_operation_test_helper(
            func=synchronized_func,
            expected_exception=exception.VolumeBackendAPIException)

    @mock.patch.object(image_utils, 'qemu_img_info')
    @mock.patch('os.path.basename')
    def _test_qemu_img_info(self, mock_basename,
                            mock_qemu_img_info, backing_file, basedir,
                            valid_backing_file=True):
        fake_vol_name = 'fake_vol_name'
        mock_info = mock_qemu_img_info.return_value
        mock_info.image = mock.sentinel.image_path
        mock_info.backing_file = backing_file

        self._driver._VALID_IMAGE_EXTENSIONS = ['vhd', 'vhdx', 'raw', 'qcow2']

        mock_basename.side_effect = [mock.sentinel.image_basename,
                                     mock.sentinel.backing_file_basename]

        if valid_backing_file:
            img_info = self._driver._qemu_img_info_base(
                mock.sentinel.image_path, fake_vol_name, basedir)
            self.assertEqual(mock_info, img_info)
            self.assertEqual(mock.sentinel.image_basename,
                             mock_info.image)
            expected_basename_calls = [mock.call(mock.sentinel.image_path)]
            if backing_file:
                self.assertEqual(mock.sentinel.backing_file_basename,
                                 mock_info.backing_file)
                expected_basename_calls.append(mock.call(backing_file))
            mock_basename.assert_has_calls(expected_basename_calls)
        else:
            self.assertRaises(exception.RemoteFSException,
                              self._driver._qemu_img_info_base,
                              mock.sentinel.image_path,
                              fake_vol_name, basedir)

        mock_qemu_img_info.assert_called_with(mock.sentinel.image_path,
                                              run_as_root=True)

    @ddt.data([None, '/fake_basedir'],
              ['/fake_basedir/cb2016/fake_vol_name', '/fake_basedir'],
              ['/fake_basedir/cb2016/fake_vol_name.VHD', '/fake_basedir'],
              ['/fake_basedir/cb2016/fake_vol_name.404f-404',
               '/fake_basedir'],
              ['/fake_basedir/cb2016/fake_vol_name.tmp-snap-404f-404',
               '/fake_basedir'])
    @ddt.unpack
    def test_qemu_img_info_valid_backing_file(self, backing_file, basedir):
        self._test_qemu_img_info(backing_file=backing_file,
                                 basedir=basedir)

    @ddt.data(['/other_random_path', '/fake_basedir'],
              ['/other_basedir/cb2016/fake_vol_name', '/fake_basedir'],
              ['/fake_basedir/invalid_hash/fake_vol_name', '/fake_basedir'],
              ['/fake_basedir/cb2016/invalid_vol_name', '/fake_basedir'],
              ['/fake_basedir/cb2016/fake_vol_name.info', '/fake_basedir'],
              ['/fake_basedir/cb2016/fake_vol_name-random-suffix',
               '/fake_basedir'],
              ['/fake_basedir/cb2016/fake_vol_name.invalidext',
               '/fake_basedir'])
    @ddt.unpack
    def test_qemu_img_info_invalid_backing_file(self, backing_file, basedir):
        self._test_qemu_img_info(backing_file=backing_file,
                                 basedir=basedir,
                                 valid_backing_file=False)

    @mock.patch.object(remotefs.RemoteFSSnapDriver, '_local_volume_dir')
    @mock.patch.object(remotefs.RemoteFSSnapDriver,
                       'get_active_image_from_info')
    def test_local_path_active_image(self, mock_get_active_img,
                                     mock_local_vol_dir):
        fake_vol_dir = 'fake_vol_dir'
        fake_active_img = 'fake_active_img_fname'

        mock_get_active_img.return_value = fake_active_img
        mock_local_vol_dir.return_value = fake_vol_dir

        active_img_path = self._driver._local_path_active_image(
            mock.sentinel.volume)
        exp_act_img_path = os.path.join(fake_vol_dir, fake_active_img)

        self.assertEqual(exp_act_img_path, active_img_path)
        mock_get_active_img.assert_called_once_with(mock.sentinel.volume)
        mock_local_vol_dir.assert_called_once_with(mock.sentinel.volume)

    @ddt.data({},
              {'provider_location': None},
              {'active_fpath': 'last_snap_img',
               'expect_snaps': True})
    @ddt.unpack
    @mock.patch.object(remotefs.RemoteFSSnapDriver,
                       '_local_path_active_image')
    @mock.patch.object(remotefs.RemoteFSSnapDriver,
                       'local_path')
    def test_snapshots_exist(self, mock_local_path,
                             mock_local_path_active_img,
                             provider_location='fake_share',
                             active_fpath='base_img_path',
                             base_vol_path='base_img_path',
                             expect_snaps=False):
        self._fake_volume.provider_location = provider_location

        mock_local_path.return_value = base_vol_path
        mock_local_path_active_img.return_value = active_fpath

        snaps_exist = self._driver._snapshots_exist(self._fake_volume)

        self.assertEqual(expect_snaps, snaps_exist)

        if provider_location:
            mock_local_path.assert_called_once_with(self._fake_volume)
            mock_local_path_active_img.assert_called_once_with(
                self._fake_volume)
        else:
            self.assertFalse(mock_local_path.called)

    @ddt.data({},
              {'snapshots_exist': True},
              {'force_temp_snap': True})
    @ddt.unpack
    @mock.patch.object(remotefs.RemoteFSSnapDriver, 'local_path')
    @mock.patch.object(remotefs.RemoteFSSnapDriver, '_snapshots_exist')
    @mock.patch.object(remotefs.RemoteFSSnapDriver, '_copy_volume_image')
    @mock.patch.object(remotefs.RemoteFSSnapDriver, '_extend_volume')
    @mock.patch.object(remotefs.RemoteFSSnapDriver, '_validate_state')
    @mock.patch.object(remotefs.RemoteFSSnapDriver, '_create_snapshot')
    @mock.patch.object(remotefs.RemoteFSSnapDriver, '_delete_snapshot')
    @mock.patch.object(remotefs.RemoteFSSnapDriver,
                       '_copy_volume_from_snapshot')
    def test_create_cloned_volume(self, mock_copy_volume_from_snapshot,
                                  mock_delete_snapshot,
                                  mock_create_snapshot,
                                  mock_validate_state,
                                  mock_extend_volme,
                                  mock_copy_volume_image,
                                  mock_snapshots_exist,
                                  mock_local_path,
                                  snapshots_exist=False,
                                  force_temp_snap=False):
        drv = self._driver

        volume = fake_volume.fake_volume_obj(self.context)
        src_vref_id = '375e32b2-804a-49f2-b282-85d1d5a5b9e1'
        src_vref = fake_volume.fake_volume_obj(
            self.context,
            id=src_vref_id,
            name='volume-%s' % src_vref_id)

        mock_snapshots_exist.return_value = snapshots_exist
        drv._always_use_temp_snap_when_cloning = force_temp_snap

        vol_attrs = ['provider_location', 'size', 'id', 'name', 'status',
                     'volume_type', 'metadata']
        Volume = collections.namedtuple('Volume', vol_attrs)

        snap_attrs = ['volume_name', 'volume_size', 'name',
                      'volume_id', 'id', 'volume']
        Snapshot = collections.namedtuple('Snapshot', snap_attrs)

        volume_ref = Volume(id=volume.id,
                            name=volume.name,
                            status=volume.status,
                            provider_location=volume.provider_location,
                            size=volume.size,
                            volume_type=volume.volume_type,
                            metadata=volume.metadata)

        snap_ref = Snapshot(volume_name=volume.name,
                            name='clone-snap-%s' % src_vref.id,
                            volume_size=src_vref.size,
                            volume_id=src_vref.id,
                            id='tmp-snap-%s' % src_vref.id,
                            volume=src_vref)

        drv.create_cloned_volume(volume, src_vref)

        exp_acceptable_states = ['available', 'backing-up', 'downloading']
        mock_validate_state.assert_called_once_with(
            src_vref.status,
            exp_acceptable_states,
            obj_description='source volume')

        if snapshots_exist or force_temp_snap:
            mock_create_snapshot.assert_called_once_with(snap_ref)
            mock_copy_volume_from_snapshot.assert_called_once_with(
                snap_ref, volume_ref, volume['size'])
            self.assertTrue(mock_delete_snapshot.called)
        else:
            self.assertFalse(mock_create_snapshot.called)

            mock_snapshots_exist.assert_called_once_with(src_vref)

            mock_copy_volume_image.assert_called_once_with(
                mock_local_path.return_value,
                mock_local_path.return_value)
            mock_local_path.assert_has_calls(
                [mock.call(src_vref), mock.call(volume_ref)])
            mock_extend_volme.assert_called_once_with(volume_ref,
                                                      volume.size)

    @mock.patch('shutil.copyfile')
    @mock.patch.object(remotefs.RemoteFSSnapDriver, '_set_rw_permissions')
    def test_copy_volume_image(self, mock_set_perm, mock_copyfile):
        self._driver._copy_volume_image(mock.sentinel.src, mock.sentinel.dest)

        mock_copyfile.assert_called_once_with(mock.sentinel.src,
                                              mock.sentinel.dest)
        mock_set_perm.assert_called_once_with(mock.sentinel.dest)

    def test_create_regular_file(self):
        self._driver._create_regular_file('/path', 1)
        self._driver._execute.assert_called_once_with('dd', 'if=/dev/zero',
                                                      'of=/path', 'bs=1M',
                                                      'count=1024',
                                                      run_as_root=True)


class RemoteFSPoolMixinTestCase(test.TestCase):
    def setUp(self):
        super(RemoteFSPoolMixinTestCase, self).setUp()
        # We'll instantiate this directly for now.
        self._driver = remotefs.RemoteFSPoolMixin()

        self.context = context.get_admin_context()

    @mock.patch.object(remotefs.RemoteFSPoolMixin,
                       '_get_pool_name_from_volume')
    @mock.patch.object(remotefs.RemoteFSPoolMixin,
                       '_get_share_from_pool_name')
    def test_find_share(self, mock_get_share_from_pool,
                        mock_get_pool_from_volume):
        share = self._driver._find_share(mock.sentinel.volume)

        self.assertEqual(mock_get_share_from_pool.return_value, share)
        mock_get_pool_from_volume.assert_called_once_with(
            mock.sentinel.volume)
        mock_get_share_from_pool.assert_called_once_with(
            mock_get_pool_from_volume.return_value)

    def test_get_pool_name_from_volume(self):
        fake_pool = 'fake_pool'
        fake_host = 'fake_host@fake_backend#%s' % fake_pool
        fake_vol = fake_volume.fake_volume_obj(
            self.context, provider_location='fake_share',
            host=fake_host)

        pool_name = self._driver._get_pool_name_from_volume(fake_vol)
        self.assertEqual(fake_pool, pool_name)

    def test_update_volume_stats(self):
        share_total_gb = 3
        share_free_gb = 2
        share_used_gb = 4  # provisioned space
        expected_allocated_gb = share_total_gb - share_free_gb

        self._driver._mounted_shares = [mock.sentinel.share]

        self._driver.configuration = mock.Mock()
        self._driver.configuration.safe_get.return_value = (
            mock.sentinel.backend_name)
        self._driver.vendor_name = mock.sentinel.vendor_name
        self._driver.driver_volume_type = mock.sentinel.driver_volume_type
        self._driver._thin_provisioning_support = (
            mock.sentinel.thin_prov_support)

        self._driver.get_version = mock.Mock(
            return_value=mock.sentinel.driver_version)
        self._driver._ensure_shares_mounted = mock.Mock()
        self._driver._get_capacity_info = mock.Mock(
            return_value=(share_total_gb << 30,
                          share_free_gb << 30,
                          share_used_gb << 30))
        self._driver._get_pool_name_from_share = mock.Mock(
            return_value=mock.sentinel.pool_name)

        expected_pool = {
            'pool_name': mock.sentinel.pool_name,
            'total_capacity_gb': float(share_total_gb),
            'free_capacity_gb': float(share_free_gb),
            'provisioned_capacity_gb': float(share_used_gb),
            'allocated_capacity_gb': float(expected_allocated_gb),
            'reserved_percentage': (
                self._driver.configuration.reserved_percentage),
            'max_over_subscription_ratio': (
                self._driver.configuration.max_over_subscription_ratio),
            'thin_provisioning_support': (
                mock.sentinel.thin_prov_support),
            'QoS_support': False,
        }

        expected_stats = {
            'volume_backend_name': mock.sentinel.backend_name,
            'vendor_name': mock.sentinel.vendor_name,
            'driver_version': mock.sentinel.driver_version,
            'storage_protocol': mock.sentinel.driver_volume_type,
            'total_capacity_gb': 0,
            'free_capacity_gb': 0,
            'pools': [expected_pool],
        }

        self._driver._update_volume_stats()

        self.assertDictEqual(expected_stats, self._driver._stats)

        self._driver._get_capacity_info.assert_called_once_with(
            mock.sentinel.share)
        self._driver.configuration.safe_get.assert_called_once_with(
            'volume_backend_name')
