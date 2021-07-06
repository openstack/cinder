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
import re
import sys
from unittest import mock

import castellan
import ddt

from cinder import context
from cinder import exception
from cinder.image import image_utils
from cinder.objects import fields
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit.keymgr import fake as fake_keymgr
from cinder.tests.unit import test
from cinder import utils
from cinder.volume.drivers import remotefs
from cinder.volume import volume_utils


class KeyObject(object):
    def get_encoded(arg):
        return "asdf".encode('utf-8')


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

        # Encrypted volume and snapshot
        self.volume_c = fake_volume.fake_volume_obj(
            self.context,
            **{'name': u'volume-0000000a',
               'id': '55555555-222f-4b32-b585-9991b3bf0a99',
               'size': 12,
               'encryption_key_id': fake.ENCRYPTION_KEY_ID})
        self._fake_snap_c = fake_snapshot.fake_snapshot_obj(self.context)
        self._fake_snap_c.volume = self.volume_c
        self.volume_c_path = os.path.join(self._FAKE_MNT_POINT,
                                          self.volume_c.name)
        self._fake_snap_c_path = (self.volume_c_path + '.' +
                                  self._fake_snap_c.id)

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
                              is_tmp_snap=False,
                              encryption=False):
        # If the snapshot is not the active image, it is guaranteed that
        # another snapshot exists having it as backing file.

        fake_upper_snap_id = 'fake_upper_snap_id'
        if encryption:
            fake_snapshot_name = os.path.basename(self._fake_snap_c_path)
            fake_info = {'active': fake_snapshot_name,
                         self._fake_snap_c.id: fake_snapshot_name}
            expected_info = fake_info

            fake_upper_snap_path = (
                self.volume_c_path + '-snapshot' + fake_upper_snap_id)

            snapshot = self._fake_snap_c
            snapshot_path = self._fake_snap_c_path
            volume_name = self.volume_c.name
        else:
            fake_snapshot_name = os.path.basename(self._fake_snapshot_path)
            fake_info = {'active': fake_snapshot_name,
                         self._fake_snapshot.id: fake_snapshot_name}
            expected_info = fake_info

            fake_upper_snap_path = (
                self._fake_volume_path + '-snapshot' + fake_upper_snap_id)

            snapshot = self._fake_snapshot
            snapshot_path = self._fake_snapshot_path
            volume_name = self._fake_volume.name

        fake_snap_img_info = mock.Mock()
        fake_base_img_info = mock.Mock()
        if stale_snapshot:
            fake_snap_img_info.backing_file = None
        else:
            fake_snap_img_info.backing_file = volume_name
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
        self._driver._delete_stale_snapshot = mock.Mock()
        self._driver._delete_snapshot_online = mock.Mock()

        exp_acceptable_states = ['available', 'in-use', 'backing-up',
                                 'deleting', 'downloading']

        if volume_in_use:
            snapshot.volume.status = 'backing-up'
            snapshot.volume.attach_status = 'attached'

            self._driver._read_info_file.return_value = fake_info

            self._driver._delete_snapshot(snapshot)
            self._driver._validate_state.assert_called_once_with(
                snapshot.volume.status,
                exp_acceptable_states)
            if stale_snapshot:
                self._driver._delete_stale_snapshot.assert_called_once_with(
                    snapshot)
            else:
                expected_online_delete_info = {
                    'active_file': fake_snapshot_name,
                    'snapshot_file': fake_snapshot_name,
                    'base_file': volume_name,
                    'base_id': None,
                    'new_base_file': None
                }
                self._driver._delete_snapshot_online.assert_called_once_with(
                    self.context, snapshot,
                    expected_online_delete_info)

        elif is_active_image:
            self._driver._read_info_file.return_value = fake_info

            self._driver._delete_snapshot(snapshot)

            self._driver._img_commit.assert_called_once_with(
                snapshot_path)
            self.assertNotIn(snapshot.id, fake_info)
            self._driver._write_info_file.assert_called_once_with(
                mock.sentinel.fake_info_path, fake_info)
        else:
            fake_upper_snap_name = os.path.basename(fake_upper_snap_path)

            fake_backing_chain = [
                {'filename': fake_upper_snap_name,
                 'backing-filename': fake_snapshot_name},
                {'filename': fake_snapshot_name,
                 'backing-filename': volume_name},
                {'filename': volume_name,
                 'backing-filename': None}]

            fake_info[fake_upper_snap_id] = fake_upper_snap_name
            fake_info[self._fake_snapshot.id] = fake_snapshot_name
            fake_info['active'] = fake_upper_snap_name

            expected_info = copy.deepcopy(fake_info)
            del expected_info[snapshot.id]

            self._driver._read_info_file.return_value = fake_info
            self._driver._get_backing_chain_for_path = mock.Mock(
                return_value=fake_backing_chain)

            self._driver._delete_snapshot(snapshot)

            self._driver._img_commit.assert_called_once_with(
                snapshot_path)
            self._driver._rebase_img.assert_called_once_with(
                fake_upper_snap_path, volume_name,
                fake_base_img_info.file_format)
            self._driver._write_info_file.assert_called_once_with(
                mock.sentinel.fake_info_path, expected_info)

    @ddt.data({'encryption': True}, {'encryption': False})
    def test_delete_snapshot_when_active_file(self, encryption):
        self._test_delete_snapshot(encryption=encryption)

    @ddt.data({'encryption': True}, {'encryption': False})
    def test_delete_snapshot_in_use(self, encryption):
        self._test_delete_snapshot(volume_in_use=True,
                                   encryption=encryption)

    @ddt.data({'encryption': True}, {'encryption': False})
    def test_delete_snapshot_in_use_stale_snapshot(self,
                                                   encryption):
        self._test_delete_snapshot(volume_in_use=True,
                                   stale_snapshot=True,
                                   encryption=encryption)

    @ddt.data({'encryption': True}, {'encryption': False})
    def test_delete_snapshot_with_one_upper_file(self,
                                                 encryption):
        self._test_delete_snapshot(is_active_image=False,
                                   encryption=encryption)

    @ddt.data({'encryption': True}, {'encryption': False})
    def test_delete_stale_snapshot(self, encryption):
        if encryption:
            fake_snapshot_name = os.path.basename(self._fake_snap_c_path)
            volume_name = self.volume_c.name
            snapshot = self._fake_snap_c
            snapshot_path = self._fake_snap_c_path
        else:
            fake_snapshot_name = os.path.basename(self._fake_snapshot_path)
            volume_name = self._fake_volume.name
            snapshot = self._fake_snapshot
            snapshot_path = self._fake_snapshot_path

        fake_snap_info = {
            'active': volume_name,
            snapshot.id: fake_snapshot_name
        }
        expected_info = {'active': volume_name}

        self._driver._local_path_volume_info = mock.Mock(
            return_value=mock.sentinel.fake_info_path)
        self._driver._read_info_file = mock.Mock(
            return_value=fake_snap_info)
        self._driver._local_volume_dir = mock.Mock(
            return_value=self._FAKE_MNT_POINT)
        self._driver._write_info_file = mock.Mock()

        self._driver._delete_stale_snapshot(snapshot)

        self._driver._delete.assert_called_once_with(snapshot_path)
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

    def _test_create_snapshot(self, display_name=None, volume_in_use=False,
                              encryption=False):
        fake_snapshot_info = {}
        if encryption:
            fake_snapshot_file_name = os.path.basename(self._fake_snap_c_path)
            volume_name = self.volume_c.name
            snapshot = self._fake_snap_c
            snapshot_path = self._fake_snap_c_path
        else:
            fake_snapshot_file_name = os.path.basename(
                self._fake_snapshot_path)
            volume_name = self._fake_volume.name
            snapshot = self._fake_snapshot
            snapshot_path = self._fake_snapshot_path

        snapshot.display_name = display_name
        self._driver._local_path_volume_info = mock.Mock(
            return_value=mock.sentinel.fake_info_path)
        self._driver._read_info_file = mock.Mock(
            return_value=fake_snapshot_info)
        self._driver._do_create_snapshot = mock.Mock()
        self._driver._create_snapshot_online = mock.Mock()
        self._driver._write_info_file = mock.Mock()
        self._driver.get_active_image_from_info = mock.Mock(
            return_value=volume_name)
        self._driver._get_new_snap_path = mock.Mock(
            return_value=snapshot_path)
        self._driver._validate_state = mock.Mock()

        expected_snapshot_info = {
            'active': fake_snapshot_file_name,
            snapshot.id: fake_snapshot_file_name
        }
        exp_acceptable_states = ['available', 'in-use', 'backing-up']
        if display_name and display_name.startswith('tmp-snap-'):
            exp_acceptable_states.append('downloading')
            self._fake_snapshot.volume.status = 'downloading'

        if volume_in_use:
            snapshot.volume.status = 'backing-up'
            snapshot.volume.attach_status = 'attached'
            expected_method_called = '_create_snapshot_online'
            conn_info = ('{"driver_volume_type": "nfs",'
                         '"export": "localhost:/srv/nfs1",'
                         '"name": "old_name"}')
            attachment = fake_volume.volume_attachment_ovo(
                self.context, connection_info=conn_info)
            snapshot.volume.volume_attachment.objects.append(attachment)
            mock_save = self.mock_object(attachment, 'save')

            # After the snapshot the connection info should change the name of
            # the file
            expected = copy.deepcopy(attachment.connection_info)
            expected['name'] = snapshot.volume.name + '.' + snapshot.id
        else:
            expected_method_called = '_do_create_snapshot'

        self._driver._create_snapshot(snapshot)

        self._driver._validate_state.assert_called_once_with(
            snapshot.volume.status,
            exp_acceptable_states)
        fake_method = getattr(self._driver, expected_method_called)
        fake_method.assert_called_with(
            snapshot, volume_name,
            snapshot_path)
        self._driver._write_info_file.assert_called_with(
            mock.sentinel.fake_info_path,
            expected_snapshot_info)

        if volume_in_use:
            mock_save.assert_called_once()
            changed_fields = attachment.cinder_obj_get_changes()
            self.assertEqual(expected, changed_fields['connection_info'])

    @ddt.data({'encryption': True}, {'encryption': False})
    def test_create_snapshot_volume_available(self, encryption):
        self._test_create_snapshot(encryption=encryption)

    @ddt.data({'encryption': True}, {'encryption': False})
    def test_create_snapshot_volume_in_use(self, encryption):
        self._test_create_snapshot(volume_in_use=True,
                                   encryption=encryption)

    def test_create_snapshot_invalid_volume(self):
        self._fake_snapshot.volume.status = 'error'
        self.assertRaises(exception.InvalidVolume,
                          self._driver._create_snapshot,
                          self._fake_snapshot)

    @ddt.data(None, 'test', 'tmp-snap-404f-404')
    def test_create_snapshot_names(self, display_name):
        self._test_create_snapshot(display_name=display_name)

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
        fake_snapshot = self._fake_snapshot
        fake_snapshot.context = self.context

        with mock.patch.object(self._driver, '_do_create_snapshot') as \
                mock_do_create_snapshot:
            self.assertRaises(exception.RemoteFSConcurrentRequest,
                              self._driver._create_snapshot_online,
                              fake_snapshot,
                              self._fake_volume.name,
                              self._fake_snapshot_path)

        mock_do_create_snapshot.assert_called_once_with(
            fake_snapshot, self._fake_volume.name,
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
                            template=None, valid_backing_file=True):
        fake_vol_name = 'fake_vol_name'
        mock_info = mock_qemu_img_info.return_value
        mock_info.image = mock.sentinel.image_path
        mock_info.backing_file = backing_file

        self._driver._VALID_IMAGE_EXTENSIONS = ['vhd', 'vhdx', 'raw', 'qcow2']

        mock_basename.side_effect = [mock.sentinel.image_basename,
                                     mock.sentinel.backing_file_basename]

        if valid_backing_file:
            img_info = self._driver._qemu_img_info_base(
                mock.sentinel.image_path, fake_vol_name, basedir,
                ext_bf_template=template)
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
            self.assertRaises(exception.RemoteFSInvalidBackingFile,
                              self._driver._qemu_img_info_base,
                              mock.sentinel.image_path,
                              fake_vol_name, basedir)

        mock_qemu_img_info.assert_called_with(mock.sentinel.image_path,
                                              force_share=False,
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

    @ddt.data([None, '/fake_basedir'],
              ['/fake_basedir/cb2016/fake_vol_name', '/fake_basedir'],
              ['/fake_basedir/cb2016/fake_vol_name.VHD', '/fake_basedir'],
              ['/fake_basedir/cb2016/fake_vol_name.404f-404',
               '/fake_basedir'],
              ['/fake_basedir/cb2016/fake_vol_name.tmp-snap-404f-404',
               '/fake_basedir'],
              ['/fake_basedir/cb2016/other_dir/404f-404',
               '/fake_basedir'],
              ['/fake_basedir/cb2016/other_dir/tmp-snap-404f-404',
               '/fake_basedir'],
              ['/fake_basedir/cb2016/other_dir/404f-404.mod1-404f-404',
               '/fake_basedir'],
              ['/fake_basedir/cb2016/other_dir/404f-404.mod2-404f-404',
               '/fake_basedir'])
    @ddt.unpack
    def test_qemu_img_info_extended_backing_file(self, backing_file, basedir):
        """Tests using a special backing file template

        The special backing file template used in here allows backing files
        in a subdirectory and with special extended names (.mod1-[], .mod2-[],
        ...).
        """
        ext_template = ("(#basedir/[0-9a-f]+/)?(#volname(.(tmp-snap-)"
                        "?[0-9a-f-]+)?#valid_ext|other_dir/(tmp-snap-)?"
                        "[0-9a-f-]+(.(mod1-|mod2-)[0-9a-f-]+)?)$")
        self._test_qemu_img_info(backing_file=backing_file,
                                 basedir=basedir,
                                 template=remotefs.BackingFileTemplate(
                                     ext_template),
                                 valid_backing_file=True)

    @ddt.data(['/other_random_path', '/fake_basedir'],
              ['/other_basedir/cb2016/fake_vol_name', '/fake_basedir'],
              ['/fake_basedir/invalid_hash/fake_vol_name', '/fake_basedir'],
              ['/fake_basedir/cb2016/invalid_vol_name', '/fake_basedir'],
              ['/fake_basedir/cb2016/fake_vol_name.info', '/fake_basedir'],
              ['/fake_basedir/cb2016/fake_vol_name-random-suffix',
               '/fake_basedir'],
              ['/fake_basedir/cb2016/fake_vol_name.invalidext',
               '/fake_basedir'],
              ['/fake_basedir/cb2016/invalid_dir/404f-404',
               '/fake_basedir'],
              ['/fake_basedir/cb2016/other_dir/invalid-prefix-404f-404',
               '/fake_basedir'],
              ['/fake_basedir/cb2016/other_dir/404f-404.mod3-404f-404',
               '/fake_basedir'],
              ['/fake_basedir/cb2016/other_dir/404f-404.mod2-404f-404.invalid',
               '/fake_basedir'])
    @ddt.unpack
    def test_qemu_img_info_extended_backing_file_invalid(self, backing_file,
                                                         basedir):
        """Tests using a special backing file template with invalid files

        The special backing file template used in here allows backing files
        in a subdirectory and with special extended names (.mod1-[], .mod2-[],
        ...).
        """
        ext_template = ("(#basedir/[0-9a-f]+/)?(#volname(.(tmp-snap-)"
                        "?[0-9a-f-]+)?#valid_ext|other_dir/(tmp-snap-)?"
                        "[0-9a-f-]+(.(mod1-|mod2-)[0-9a-f-]+)?)$")
        self._test_qemu_img_info(backing_file=backing_file,
                                 basedir=basedir,
                                 template=remotefs.BackingFileTemplate(
                                     ext_template),
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
    @mock.patch.object(sys.modules['cinder.objects'], "Snapshot")
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
                                  mock_extend_volume,
                                  mock_copy_volume_image,
                                  mock_snapshots_exist,
                                  mock_local_path,
                                  mock_obj_snap,
                                  snapshots_exist=False,
                                  force_temp_snap=False):
        drv = self._driver

        # prepare test
        volume = fake_volume.fake_volume_obj(self.context)
        src_vref_id = '375e32b2-804a-49f2-b282-85d1d5a5b9e1'
        src_vref = fake_volume.fake_volume_obj(
            self.context,
            id=src_vref_id,
            name='volume-%s' % src_vref_id,
            obj_context=self.context)
        src_vref.context = self.context

        mock_snapshots_exist.return_value = snapshots_exist
        drv._always_use_temp_snap_when_cloning = force_temp_snap

        vol_attrs = ['provider_location', 'size', 'id', 'name', 'status',
                     'volume_type', 'metadata', 'obj_context']
        Volume = collections.namedtuple('Volume', vol_attrs)

        volume_ref = Volume(id=volume.id,
                            metadata=volume.metadata,
                            name=volume.name,
                            provider_location=volume.provider_location,
                            status=volume.status,
                            size=volume.size,
                            volume_type=volume.volume_type,
                            obj_context=self.context,)

        snap_args_creation = {
            'volume_id': src_vref.id,
            'user_id': None,
            'project_id': None,
            'status': fields.SnapshotStatus.CREATING,
            'progress': '0%',
            'volume_size': src_vref.size,
            'display_name': 'tmp-snap-%s' % volume.id,
            'display_description': None,
            'volume_type_id': src_vref.volume_type_id,
            'encryption_key_id': None,
        }
        snap_args_deletion = snap_args_creation.copy()
        snap_args_deletion["status"] = fields.SnapshotStatus.DELETED
        snap_args_deletion["deleted"] = True

        mock_obj_snap.return_value = mock.Mock()
        mock_obj_snap.return_value.create = mock.Mock()
        # end of prepare test

        # run test
        drv.create_cloned_volume(volume, src_vref)

        # evaluate test
        exp_acceptable_states = ['available', 'backing-up', 'downloading']
        mock_validate_state.assert_called_once_with(
            src_vref.status,
            exp_acceptable_states,
            obj_description='source volume')

        if snapshots_exist or force_temp_snap:
            mock_obj_snap.return_value.create.assert_called_once_with()
            mock_obj_snap.assert_called_once_with(
                context=self.context, **snap_args_creation)
            mock_create_snapshot.assert_called_once_with(
                mock_obj_snap.return_value)
            mock_copy_volume_from_snapshot.assert_called_once_with(
                mock_obj_snap.return_value, volume_ref, volume['size'],
                src_encryption_key_id=None, new_encryption_key_id=None)
            mock_delete_snapshot.called_once_with(snap_args_deletion)
        else:
            self.assertFalse(mock_create_snapshot.called)

            mock_snapshots_exist.assert_called_once_with(src_vref)

            mock_copy_volume_image.assert_called_once_with(
                mock_local_path.return_value,
                mock_local_path.return_value)
            mock_local_path.assert_has_calls(
                [mock.call(src_vref), mock.call(volume_ref)])
            mock_extend_volume.assert_called_once_with(volume_ref, volume.size)

    @ddt.data(None, 'raw', 'qcow2')
    @mock.patch('cinder.objects.volume.Volume.save')
    @mock.patch.object(sys.modules['cinder.objects'], "Snapshot")
    @mock.patch.object(remotefs.RemoteFSSnapDriver, 'local_path')
    @mock.patch.object(remotefs.RemoteFSSnapDriver, '_snapshots_exist')
    @mock.patch.object(remotefs.RemoteFSSnapDriver, '_copy_volume_image')
    @mock.patch.object(remotefs.RemoteFSSnapDriver, '_extend_volume')
    @mock.patch.object(remotefs.RemoteFSSnapDriver, '_validate_state')
    @mock.patch.object(remotefs.RemoteFSSnapDriver, '_create_snapshot')
    @mock.patch.object(remotefs.RemoteFSSnapDriver, '_delete_snapshot')
    @mock.patch.object(remotefs.RemoteFSSnapDriver,
                       '_copy_volume_from_snapshot')
    def test_create_cloned_volume_with_format(
            self, file_format, mock_copy_volume_from_snapshot,
            mock_delete_snapshot, mock_create_snapshot,
            mock_validate_state, mock_extend_volume,
            mock_copy_volume_image, mock_snapshots_exist,
            mock_local_path, mock_obj_snap, mock_save):
        drv = self._driver

        # prepare test
        volume = fake_volume.fake_volume_obj(self.context)
        src_vref_id = '375e32b2-804a-49f2-b282-85d1d5a5b9e1'
        src_vref = fake_volume.fake_volume_obj(
            self.context,
            id=src_vref_id,
            name='volume-%s' % src_vref_id,
            obj_context=self.context)
        src_vref.context = self.context
        if file_format:
            src_vref.admin_metadata = {'format': file_format}

        mock_snapshots_exist.return_value = False
        drv._always_use_temp_snap_when_cloning = False

        vol_attrs = ['provider_location', 'size', 'id', 'name', 'status',
                     'volume_type', 'metadata', 'obj_context']
        Volume = collections.namedtuple('Volume', vol_attrs)

        volume_ref = Volume(id=volume.id,
                            metadata=volume.metadata,
                            name=volume.name,
                            provider_location=volume.provider_location,
                            status=volume.status,
                            size=volume.size,
                            volume_type=volume.volume_type,
                            obj_context=self.context,)

        snap_args_creation = {
            'volume_id': src_vref.id,
            'user_id': None,
            'project_id': None,
            'status': fields.SnapshotStatus.CREATING,
            'progress': '0%',
            'volume_size': src_vref.size,
            'display_name': 'tmp-snap-%s' % volume.id,
            'display_description': None,
            'volume_type_id': src_vref.volume_type_id,
            'encryption_key_id': None,
        }
        snap_args_deletion = snap_args_creation.copy()
        snap_args_deletion["status"] = fields.SnapshotStatus.DELETED
        snap_args_deletion["deleted"] = True

        mock_obj_snap.return_value = mock.Mock()
        mock_obj_snap.return_value.create = mock.Mock()
        # end of prepare test

        # run test
        drv.create_cloned_volume(volume, src_vref)

        # evaluate test
        exp_acceptable_states = ['available', 'backing-up', 'downloading']
        mock_validate_state.assert_called_once_with(
            src_vref.status,
            exp_acceptable_states,
            obj_description='source volume')

        self.assertFalse(mock_create_snapshot.called)

        mock_snapshots_exist.assert_called_once_with(src_vref)

        mock_copy_volume_image.assert_called_once_with(
            mock_local_path.return_value,
            mock_local_path.return_value)
        mock_local_path.assert_has_calls(
            [mock.call(src_vref), mock.call(volume_ref)])
        mock_extend_volume.assert_called_once_with(volume_ref, volume.size)
        if file_format:
            self.assertEqual(file_format,
                             volume.admin_metadata['format'])

    @mock.patch('tempfile.NamedTemporaryFile')
    @mock.patch('cinder.volume.volume_utils.check_encryption_provider',
                return_value={'encryption_key_id': fake.ENCRYPTION_KEY_ID})
    def test_create_encrypted_volume(self,
                                     mock_check_enc_prov,
                                     mock_temp_file):
        class DictObj(object):
            # convert a dict to object w/ attributes
            def __init__(self, d):
                self.__dict__ = d

        drv = self._driver

        mock_temp_file.return_value.__enter__.side_effect = [
            DictObj({'name': '/imgfile'}),
            DictObj({'name': '/passfile'})]

        key_mgr = fake_keymgr.fake_api()

        self.mock_object(castellan.key_manager, 'API', return_value=key_mgr)
        key_id = key_mgr.store(self.context, KeyObject())
        self.volume_c.encryption_key_id = key_id

        enc_info = {'encryption_key_id': key_id,
                    'cipher': 'aes-xts-essiv',
                    'key_size': 256}

        remotefs_path = 'cinder.volume.drivers.remotefs.open'
        with mock.patch('cinder.volume.volume_utils.check_encryption_provider',
                        return_value=enc_info), \
                mock.patch(remotefs_path) as mock_open, \
                mock.patch.object(drv, '_execute') as mock_exec:

            drv._create_encrypted_volume_file("/passfile",
                                              self.volume_c.size,
                                              enc_info,
                                              self.context)

            mock_open.assert_called_with('/imgfile', 'w')
            mock_exec.assert_called()

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

    @mock.patch.object(remotefs.RemoteFSSnapDriver, '_local_path_volume_info')
    @mock.patch.object(remotefs.RemoteFSSnapDriver, '_read_info_file')
    @mock.patch.object(remotefs.RemoteFSSnapDriver, '_local_volume_dir')
    @mock.patch.object(remotefs.RemoteFSSnapDriver, '_qemu_img_info')
    def test_get_snapshot_backing_file(
            self, mock_qemu_img_info, mock_local_vol_dir,
            mock_read_info_file, mock_local_path_vol_info):

        fake_snapshot_file_name = os.path.basename(self._fake_snapshot_path)
        fake_snapshot_info = {self._fake_snapshot.id: fake_snapshot_file_name}

        fake_snap_img_info = mock.Mock()
        fake_snap_img_info.backing_file = self._fake_volume.name

        mock_read_info_file.return_value = fake_snapshot_info
        mock_qemu_img_info.return_value = fake_snap_img_info
        mock_local_vol_dir.return_value = self._FAKE_MNT_POINT

        snap_backing_file = self._driver._get_snapshot_backing_file(
            self._fake_snapshot)
        self.assertEqual(os.path.basename(self._fake_volume_path),
                         snap_backing_file)

        mock_local_path_vol_info.assert_called_once_with(self._fake_volume)
        mock_read_info_file.assert_called_once_with(
            mock_local_path_vol_info.return_value)
        mock_local_vol_dir.assert_called_once_with(self._fake_volume)
        mock_qemu_img_info.assert_called_once_with(self._fake_snapshot_path)

    @ddt.data({},
              {'info_file_exists': True},
              {'os_name': 'nt'})
    @ddt.unpack
    @mock.patch('json.dump')
    @mock.patch('cinder.volume.drivers.remotefs.open')
    @mock.patch('os.path.exists')
    def test_write_info_file(self,
                             mock_os_path_exists,
                             mock_open,
                             mock_json_dump,
                             info_file_exists=False,
                             os_name='posix'):

        mock_os_path_exists.return_value = info_file_exists
        fake_info_path = '/path/to/info'
        fake_snapshot_info = {'active': self._fake_snapshot_path}
        self._driver._execute = mock.Mock()
        self._driver._set_rw_permissions = mock.Mock()

        self._driver._write_info_file(fake_info_path, fake_snapshot_info)

        mock_open.assert_called_once_with(fake_info_path, 'w')
        mock_json_dump.assert_called_once_with(
            fake_snapshot_info, mock.ANY, indent=1, sort_keys=True)

        if info_file_exists or os.name == 'nt':
            self._driver._execute.assert_not_called()
            self._driver._set_rw_permissions.assert_not_called()
        else:
            self._driver._execute.assert_called_once_with(
                'truncate', "-s0", fake_info_path,
                run_as_root=self._driver._execute_as_root)
            self._driver._set_rw_permissions.assert_called_once_with(
                fake_info_path)

        fake_snapshot_info.pop('active')
        self.assertRaises(exception.RemoteFSException,
                          self._driver._write_info_file,
                          fake_info_path,
                          fake_snapshot_info)


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

        self._driver._mounted_shares = [mock.sentinel.share]

        self._driver.configuration = mock.Mock()
        self._driver.configuration.safe_get.return_value = (
            mock.sentinel.backend_name)
        self._driver.vendor_name = mock.sentinel.vendor_name
        self._driver.driver_volume_type = mock.sentinel.driver_volume_type
        self._driver._thin_provisioning_support = (
            mock.sentinel.thin_prov_support)
        self._driver._thick_provisioning_support = (
            mock.sentinel.thick_prov_support)

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
            'reserved_percentage': (
                self._driver.configuration.reserved_percentage),
            'max_over_subscription_ratio': (
                self._driver.configuration.max_over_subscription_ratio),
            'thin_provisioning_support': (
                mock.sentinel.thin_prov_support),
            'thick_provisioning_support': (
                mock.sentinel.thick_prov_support),
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


@ddt.ddt
class RevertToSnapshotMixinTestCase(test.TestCase):

    _FAKE_MNT_POINT = '/mnt/fake_hash'

    def setUp(self):
        super(RevertToSnapshotMixinTestCase, self).setUp()
        self._driver = remotefs.RevertToSnapshotMixin()
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
        self._fake_snapshot_name = os.path.basename(
            self._fake_snapshot_path)
        self._fake_snapshot.volume = self._fake_volume

    @ddt.data(True, False)
    @mock.patch.object(remotefs.RevertToSnapshotMixin, '_validate_state',
                       create=True)
    @mock.patch.object(remotefs.RevertToSnapshotMixin, '_read_info_file',
                       create=True)
    @mock.patch.object(remotefs.RevertToSnapshotMixin,
                       '_local_path_volume_info', create=True)
    @mock.patch.object(remotefs.RevertToSnapshotMixin, '_qemu_img_info',
                       create=True)
    @mock.patch.object(remotefs.RevertToSnapshotMixin, '_do_create_snapshot',
                       create=True)
    @mock.patch.object(remotefs.RevertToSnapshotMixin, '_local_volume_dir',
                       create=True)
    def test_revert_to_snapshot(self,
                                is_latest_snapshot,
                                mock_local_vol_dir,
                                mock_do_create_snapshot,
                                mock_qemu_img_info,
                                mock_local_path_vol_info,
                                mock_read_info_file,
                                mock_validate_state):

        active_file = (self._fake_snapshot_name if is_latest_snapshot
                       else 'fake_latest_snap')
        fake_snapshot_info = {
            'active': active_file,
            self._fake_snapshot.id: self._fake_snapshot_name
        }

        mock_read_info_file.return_value = fake_snapshot_info

        fake_snap_img_info = mock.Mock()
        fake_snap_img_info.backing_file = self._fake_volume.name

        mock_qemu_img_info.return_value = fake_snap_img_info
        mock_local_vol_dir.return_value = self._FAKE_MNT_POINT

        if is_latest_snapshot:
            self._driver._revert_to_snapshot(self.context, self._fake_volume,
                                             self._fake_snapshot)
            self._driver._delete.assert_called_once_with(
                self._fake_snapshot_path)
            mock_do_create_snapshot.assert_called_once_with(
                self._fake_snapshot,
                fake_snap_img_info.backing_file,
                self._fake_snapshot_path)
            mock_qemu_img_info.assert_called_once_with(
                self._fake_snapshot_path,
                self._fake_volume.name)
        elif not is_latest_snapshot:
            self.assertRaises(exception.InvalidSnapshot,
                              self._driver._revert_to_snapshot,
                              self.context, self._fake_volume,
                              self._fake_snapshot)
            self._driver._delete.assert_not_called()

        exp_acceptable_states = ['available', 'reverting']
        mock_validate_state.assert_called_once_with(
            self._fake_snapshot.volume.status,
            exp_acceptable_states)
        mock_local_path_vol_info.assert_called_once_with(
            self._fake_snapshot.volume)
        mock_read_info_file.assert_called_once_with(
            mock_local_path_vol_info.return_value)


@ddt.ddt
class RemoteFSManageableVolumesTestCase(test.TestCase):
    def setUp(self):
        super(RemoteFSManageableVolumesTestCase, self).setUp()
        # We'll instantiate this directly for now.
        self._driver = remotefs.RemoteFSManageableVolumesMixin()

    @mock.patch.object(remotefs.RemoteFSManageableVolumesMixin,
                       '_get_mount_point_for_share', create=True)
    @mock.patch.object(os.path, 'isfile')
    def test_get_manageable_vol_location_invalid(self, mock_is_file,
                                                 mock_get_mount_point):
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self._driver._get_manageable_vol_location,
                          {})

        self._driver._mounted_shares = []
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self._driver._get_manageable_vol_location,
                          {'source-name': '//hots/share/img'})

        self._driver._mounted_shares = ['//host/share']
        mock_get_mount_point.return_value = '/fake_mountpoint'
        mock_is_file.return_value = False

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self._driver._get_manageable_vol_location,
                          {'source-name': '//host/share/subdir/img'})
        mock_is_file.assert_any_call(
            os.path.normpath('/fake_mountpoint/subdir/img'))

    @mock.patch.object(remotefs.RemoteFSManageableVolumesMixin,
                       '_get_mount_point_for_share', create=True)
    @mock.patch.object(os.path, 'isfile')
    def test_get_manageable_vol_location(self, mock_is_file,
                                         mock_get_mount_point):
        self._driver._mounted_shares = [
            '//host/share2/subdir',
            '//host/share/subdir',
            'host:/dir/subdir'
        ]

        mock_get_mount_point.return_value = '/fake_mountpoint'
        mock_is_file.return_value = True

        location_info = self._driver._get_manageable_vol_location(
            {'source-name': 'host:/dir/subdir/import/img'})

        exp_location_info = {
            'share': 'host:/dir/subdir',
            'mountpoint': mock_get_mount_point.return_value,
            'vol_local_path': '/fake_mountpoint/import/img',
            'vol_remote_path': 'host:/dir/subdir/import/img'
        }
        self.assertEqual(exp_location_info, location_info)

    @mock.patch.object(remotefs.RemoteFSManageableVolumesMixin,
                       '_get_mount_point_for_share', create=True)
    @mock.patch.object(os.path, 'isfile')
    @mock.patch.object(os.path, 'normpath', lambda x: x.replace('/', '\\'))
    @mock.patch.object(os.path, 'normcase', lambda x: x.lower())
    @mock.patch.object(os.path, 'join', lambda *args: '\\'.join(args))
    @mock.patch.object(os.path, 'sep', '\\')
    def test_get_manageable_vol_location_win32(self, mock_is_file,
                                               mock_get_mount_point):
        self._driver._mounted_shares = [
            '//host/share2/subdir',
            '//host/share/subdir',
            'host:/dir/subdir'
        ]

        mock_get_mount_point.return_value = r'c:\fake_mountpoint'
        mock_is_file.return_value = True

        location_info = self._driver._get_manageable_vol_location(
            {'source-name': '//Host/share/Subdir/import/img'})

        exp_location_info = {
            'share': '//host/share/subdir',
            'mountpoint': mock_get_mount_point.return_value,
            'vol_local_path': r'c:\fake_mountpoint\import\img',
            'vol_remote_path': r'\\host\share\subdir\import\img'
        }
        self.assertEqual(exp_location_info, location_info)

    def test_get_managed_vol_exp_path(self):
        fake_vol = fake_volume.fake_volume_obj(mock.sentinel.context)
        vol_location = dict(mountpoint='fake-mountpoint')

        exp_path = os.path.join(vol_location['mountpoint'],
                                fake_vol.name)
        ret_val = self._driver._get_managed_vol_expected_path(
            fake_vol, vol_location)
        self.assertEqual(exp_path, ret_val)

    @ddt.data(
        {'already_managed': True},
        {'qemu_side_eff': exception.RemoteFSInvalidBackingFile},
        {'qemu_side_eff': Exception},
        {'qemu_side_eff': [mock.Mock(backing_file=None,
                                     file_format='fakefmt')]},
        {'qemu_side_eff': [mock.Mock(backing_file='backing_file',
                                     file_format='raw')]}
    )
    @ddt.unpack
    @mock.patch.object(remotefs.RemoteFSManageableVolumesMixin,
                       '_qemu_img_info', create=True)
    def test_check_unmanageable_volume(self, mock_qemu_info,
                                       qemu_side_eff=None,
                                       already_managed=False):
        mock_qemu_info.side_effect = qemu_side_eff

        manageable = self._driver._is_volume_manageable(
            mock.sentinel.volume_path,
            already_managed=already_managed)[0]
        self.assertFalse(manageable)

    @mock.patch.object(remotefs.RemoteFSManageableVolumesMixin,
                       '_qemu_img_info', create=True)
    def test_check_manageable_volume(self, mock_qemu_info,
                                     qemu_side_eff=None,
                                     already_managed=False):
        mock_qemu_info.return_value = mock.Mock(
            backing_file=None,
            file_format='raw')

        manageable = self._driver._is_volume_manageable(
            mock.sentinel.volume_path)[0]
        self.assertTrue(manageable)

    @mock.patch.object(remotefs.RemoteFSManageableVolumesMixin,
                       '_get_manageable_vol_location')
    @mock.patch.object(remotefs.RemoteFSManageableVolumesMixin,
                       '_is_volume_manageable')
    def test_manage_existing_unmanageable(self, mock_check_manageable,
                                          mock_get_location):
        fake_vol = fake_volume.fake_volume_obj(mock.sentinel.context)

        mock_get_location.return_value = dict(
            vol_local_path=mock.sentinel.local_path)
        mock_check_manageable.return_value = False, mock.sentinel.resason

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self._driver.manage_existing,
                          fake_vol,
                          mock.sentinel.existing_ref)
        mock_get_location.assert_called_once_with(mock.sentinel.existing_ref)
        mock_check_manageable.assert_called_once_with(
            mock.sentinel.local_path)

    @mock.patch.object(remotefs.RemoteFSManageableVolumesMixin,
                       '_get_manageable_vol_location')
    @mock.patch.object(remotefs.RemoteFSManageableVolumesMixin,
                       '_is_volume_manageable')
    @mock.patch.object(remotefs.RemoteFSManageableVolumesMixin,
                       '_set_rw_permissions', create=True)
    @mock.patch.object(remotefs.RemoteFSManageableVolumesMixin,
                       '_get_managed_vol_expected_path')
    @mock.patch.object(os, 'rename')
    def test_manage_existing_manageable(self, mock_rename,
                                        mock_get_exp_path,
                                        mock_set_perm,
                                        mock_check_manageable,
                                        mock_get_location):
        fake_vol = fake_volume.fake_volume_obj(mock.sentinel.context)

        mock_get_location.return_value = dict(
            vol_local_path=mock.sentinel.local_path,
            share=mock.sentinel.share)
        mock_check_manageable.return_value = True, None

        exp_ret_val = {'provider_location': mock.sentinel.share}
        ret_val = self._driver.manage_existing(fake_vol,
                                               mock.sentinel.existing_ref)
        self.assertEqual(exp_ret_val, ret_val)

        mock_get_exp_path.assert_called_once_with(
            fake_vol, mock_get_location.return_value)
        mock_set_perm.assert_called_once_with(mock.sentinel.local_path)
        mock_rename.assert_called_once_with(mock.sentinel.local_path,
                                            mock_get_exp_path.return_value)

    @mock.patch.object(image_utils, 'qemu_img_info')
    def _get_rounded_manageable_image_size(self, mock_qemu_info):
        mock_qemu_info.return_value.virtual_size = 1 << 30 + 1
        exp_rounded_size_gb = 2

        size = self._driver._get_rounded_manageable_image_size(
            mock.sentinel.image_path)
        self.assertEqual(exp_rounded_size_gb, size)

        mock_qemu_info.assert_called_once_with(mock.sentinel.image_path)

    @mock.patch.object(remotefs.RemoteFSManageableVolumesMixin,
                       '_get_manageable_vol_location')
    @mock.patch.object(remotefs.RemoteFSManageableVolumesMixin,
                       '_get_rounded_manageable_image_size')
    def test_manage_existing_get_size(self, mock_get_size,
                                      mock_get_location):
        mock_get_location.return_value = dict(
            vol_local_path=mock.sentinel.image_path)

        size = self._driver.manage_existing_get_size(
            mock.sentinel.volume,
            mock.sentinel.existing_ref)
        self.assertEqual(mock_get_size.return_value, size)

        mock_get_location.assert_called_once_with(mock.sentinel.existing_ref)
        mock_get_size.assert_called_once_with(mock.sentinel.image_path)

    @ddt.data(
        {},
        {'managed_volume': mock.Mock(size=mock.sentinel.sz),
         'exp_size': mock.sentinel.sz,
         'manageable_check_ret_val': False,
         'exp_manageable': False},
        {'exp_size': None,
         'get_size_side_effect': Exception,
         'exp_manageable': False})
    @ddt.unpack
    @mock.patch.object(remotefs.RemoteFSManageableVolumesMixin,
                       '_is_volume_manageable')
    @mock.patch.object(remotefs.RemoteFSManageableVolumesMixin,
                       '_get_rounded_manageable_image_size')
    @mock.patch.object(remotefs.RemoteFSManageableVolumesMixin,
                       '_get_mount_point_for_share', create=True)
    def test_get_manageable_volume(
            self, mock_get_mount_point,
            mock_get_size, mock_check_manageable,
            managed_volume=None,
            get_size_side_effect=(mock.sentinel.size_gb, ),
            manageable_check_ret_val=True,
            exp_size=mock.sentinel.size_gb,
            exp_manageable=True):
        share = '//host/share'
        mountpoint = '/fake-mountpoint'
        volume_path = '/fake-mountpoint/subdir/vol'

        exp_ret_val = {
            'reference': {'source-name': '//host/share/subdir/vol'},
            'size': exp_size,
            'safe_to_manage': exp_manageable,
            'reason_not_safe': mock.ANY,
            'cinder_id': managed_volume.id if managed_volume else None,
            'extra_info': None,
        }

        mock_get_size.side_effect = get_size_side_effect
        mock_check_manageable.return_value = (manageable_check_ret_val,
                                              mock.sentinel.reason)
        mock_get_mount_point.return_value = mountpoint

        ret_val = self._driver._get_manageable_volume(
            share, volume_path, managed_volume)
        self.assertEqual(exp_ret_val, ret_val)

        mock_check_manageable.assert_called_once_with(
            volume_path, already_managed=managed_volume is not None)
        mock_get_mount_point.assert_called_once_with(share)
        if managed_volume:
            mock_get_size.assert_not_called()
        else:
            mock_get_size.assert_called_once_with(volume_path)

    @mock.patch.object(remotefs.RemoteFSManageableVolumesMixin,
                       '_get_mount_point_for_share', create=True)
    @mock.patch.object(remotefs.RemoteFSManageableVolumesMixin,
                       '_get_manageable_volume')
    @mock.patch.object(os, 'walk')
    @mock.patch.object(os.path, 'join', lambda *args: '/'.join(args))
    def test_get_share_manageable_volumes(
            self, mock_walk, mock_get_manageable_volume,
            mock_get_mount_point):
        mount_path = '/fake-mountpoint'
        mock_walk.return_value = [
            [mount_path, ['subdir'], ['volume-1.vhdx']],
            ['/fake-mountpoint/subdir', [], ['volume-0', 'volume-3.vhdx']]]

        mock_get_manageable_volume.side_effect = [
            Exception,
            mock.sentinel.managed_volume]

        self._driver._MANAGEABLE_IMAGE_RE = re.compile(r'.*\.(?:vhdx)$')

        managed_volumes = {'volume-1': mock.sentinel.vol1}

        exp_manageable = [mock.sentinel.managed_volume]
        manageable_volumes = self._driver._get_share_manageable_volumes(
            mock.sentinel.share,
            managed_volumes)

        self.assertEqual(exp_manageable, manageable_volumes)

        mock_get_manageable_volume.assert_has_calls(
            [mock.call(mock.sentinel.share,
                       '/fake-mountpoint/volume-1.vhdx',
                       mock.sentinel.vol1),
             mock.call(mock.sentinel.share,
                       '/fake-mountpoint/subdir/volume-3.vhdx',
                       None)])

    @mock.patch.object(remotefs.RemoteFSManageableVolumesMixin,
                       '_get_share_manageable_volumes')
    @mock.patch.object(volume_utils, 'paginate_entries_list')
    def test_get_manageable_volumes(self, mock_paginate, mock_get_share_vols):
        fake_vol = fake_volume.fake_volume_obj(mock.sentinel.context)
        self._driver._mounted_shares = [mock.sentinel.share0,
                                        mock.sentinel.share1]

        mock_get_share_vols.side_effect = [
            Exception, [mock.sentinel.manageable_vol]]

        pagination_args = [
            mock.sentinel.marker, mock.sentinel.limit,
            mock.sentinel.offset, mock.sentinel.sort_keys,
            mock.sentinel.sort_dirs]
        ret_val = self._driver.get_manageable_volumes(
            [fake_vol], *pagination_args)

        self.assertEqual(mock_paginate.return_value, ret_val)
        mock_paginate.assert_called_once_with(
            [mock.sentinel.manageable_vol], *pagination_args)

        exp_managed_vols_dict = {fake_vol.name: fake_vol}
        mock_get_share_vols.assert_has_calls(
            [mock.call(share, exp_managed_vols_dict)
             for share in self._driver._mounted_shares])
