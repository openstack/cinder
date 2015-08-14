
# Copyright (c) 2013 eNovance , Inc.
# All Rights Reserved.
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
"""Unit tests for image utils."""

import math

import mock
from oslo_concurrency import processutils
from oslo_utils import units

from cinder import exception
from cinder.image import image_utils
from cinder import test
from cinder.volume import throttling


class TestQemuImgInfo(test.TestCase):
    @mock.patch('cinder.openstack.common.imageutils.QemuImgInfo')
    @mock.patch('cinder.utils.execute')
    def test_qemu_img_info(self, mock_exec, mock_info):
        mock_out = mock.sentinel.out
        mock_err = mock.sentinel.err
        test_path = mock.sentinel.path
        mock_exec.return_value = (mock_out, mock_err)

        output = image_utils.qemu_img_info(test_path)
        mock_exec.assert_called_once_with('env', 'LC_ALL=C', 'qemu-img',
                                          'info', test_path, run_as_root=True)
        self.assertEqual(mock_info.return_value, output)

    @mock.patch('cinder.openstack.common.imageutils.QemuImgInfo')
    @mock.patch('cinder.utils.execute')
    def test_qemu_img_info_not_root(self, mock_exec, mock_info):
        mock_out = mock.sentinel.out
        mock_err = mock.sentinel.err
        test_path = mock.sentinel.path
        mock_exec.return_value = (mock_out, mock_err)

        output = image_utils.qemu_img_info(test_path, run_as_root=False)
        mock_exec.assert_called_once_with('env', 'LC_ALL=C', 'qemu-img',
                                          'info', test_path, run_as_root=False)
        self.assertEqual(mock_info.return_value, output)

    @mock.patch('cinder.image.image_utils.os')
    @mock.patch('cinder.openstack.common.imageutils.QemuImgInfo')
    @mock.patch('cinder.utils.execute')
    def test_qemu_img_info_on_nt(self, mock_exec, mock_info, mock_os):
        mock_out = mock.sentinel.out
        mock_err = mock.sentinel.err
        test_path = mock.sentinel.path
        mock_exec.return_value = (mock_out, mock_err)
        mock_os.name = 'nt'

        output = image_utils.qemu_img_info(test_path)
        mock_exec.assert_called_once_with('qemu-img', 'info', test_path,
                                          run_as_root=True)
        self.assertEqual(mock_info.return_value, output)

    @mock.patch('cinder.utils.execute')
    def test_get_qemu_img_version(self, mock_exec):
        mock_out = "qemu-img version 2.0.0"
        mock_err = mock.sentinel.err
        mock_exec.return_value = (mock_out, mock_err)

        expected_version = [2, 0, 0]
        version = image_utils.get_qemu_img_version()

        mock_exec.assert_called_once_with('qemu-img', '--help',
                                          check_exit_code=False)
        self.assertEqual(expected_version, version)

    @mock.patch.object(image_utils, 'get_qemu_img_version')
    def test_validate_qemu_img_version(self, mock_get_qemu_img_version):
        fake_current_version = [1, 8]
        mock_get_qemu_img_version.return_value = fake_current_version
        minimum_version = '1.8'

        image_utils.check_qemu_img_version(minimum_version)

        mock_get_qemu_img_version.assert_called_once_with()

    @mock.patch.object(image_utils, 'get_qemu_img_version')
    def _test_validate_unsupported_qemu_img_version(self,
                                                    mock_get_qemu_img_version,
                                                    current_version=None):
        mock_get_qemu_img_version.return_value = current_version
        minimum_version = '2.0'

        self.assertRaises(exception.VolumeBackendAPIException,
                          image_utils.check_qemu_img_version,
                          minimum_version)

        mock_get_qemu_img_version.assert_called_once_with()

    def test_validate_qemu_img_version_not_installed(self):
        self._test_validate_unsupported_qemu_img_version()

    def test_validate_older_qemu_img_version(self):
        self._test_validate_unsupported_qemu_img_version(
            current_version=[1, 8])


class TestConvertImage(test.TestCase):
    @mock.patch('cinder.image.image_utils.os.stat')
    @mock.patch('cinder.utils.execute')
    @mock.patch('cinder.utils.is_blk_device', return_value=True)
    def test_defaults_block_dev(self, mock_isblk, mock_exec,
                                mock_stat):
        source = mock.sentinel.source
        dest = mock.sentinel.dest
        out_format = mock.sentinel.out_format
        mock_stat.return_value.st_size = 1048576
        throttle = throttling.Throttle(prefix=['cgcmd'])

        with mock.patch('cinder.volume.utils.check_for_odirect_support',
                        return_value=True):
            output = image_utils.convert_image(source, dest, out_format,
                                               throttle=throttle)

            self.assertIsNone(output)
            mock_exec.assert_called_once_with('cgcmd', 'qemu-img', 'convert',
                                              '-t', 'none', '-O', out_format,
                                              source, dest, run_as_root=True)

        mock_exec.reset_mock()

        with mock.patch('cinder.volume.utils.check_for_odirect_support',
                        return_value=False):
            output = image_utils.convert_image(source, dest, out_format)

            self.assertIsNone(output)
            mock_exec.assert_called_once_with('qemu-img', 'convert',
                                              '-O', out_format, source, dest,
                                              run_as_root=True)

    @mock.patch('cinder.volume.utils.check_for_odirect_support',
                return_value=True)
    @mock.patch('cinder.image.image_utils.os.stat')
    @mock.patch('cinder.utils.execute')
    @mock.patch('cinder.utils.is_blk_device', return_value=False)
    def test_defaults_not_block_dev(self, mock_isblk, mock_exec,
                                    mock_stat, mock_odirect):
        source = mock.sentinel.source
        dest = mock.sentinel.dest
        out_format = mock.sentinel.out_format
        mock_stat.return_value.st_size = 1048576

        output = image_utils.convert_image(source, dest, out_format)

        self.assertIsNone(output)
        mock_exec.assert_called_once_with('qemu-img', 'convert', '-O',
                                          out_format, source, dest,
                                          run_as_root=True)


class TestResizeImage(test.TestCase):
    @mock.patch('cinder.utils.execute')
    def test_defaults(self, mock_exec):
        source = mock.sentinel.source
        size = mock.sentinel.size
        output = image_utils.resize_image(source, size)
        self.assertIsNone(output)
        mock_exec.assert_called_once_with('qemu-img', 'resize', source,
                                          'sentinel.sizeG', run_as_root=False)

    @mock.patch('cinder.utils.execute')
    def test_run_as_root(self, mock_exec):
        source = mock.sentinel.source
        size = mock.sentinel.size
        output = image_utils.resize_image(source, size, run_as_root=True)
        self.assertIsNone(output)
        mock_exec.assert_called_once_with('qemu-img', 'resize', source,
                                          'sentinel.sizeG', run_as_root=True)


class TestFetch(test.TestCase):
    @mock.patch('os.stat')
    @mock.patch('cinder.image.image_utils.fileutils')
    def test_defaults(self, mock_fileutils, mock_stat):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_id = mock.sentinel.image_id
        path = 'test_path'
        _user_id = mock.sentinel._user_id
        _project_id = mock.sentinel._project_id
        mock_open = mock.mock_open()
        mock_stat.return_value.st_size = 1048576

        with mock.patch('cinder.image.image_utils.open',
                        new=mock_open, create=True):
            output = image_utils.fetch(ctxt, image_service, image_id, path,
                                       _user_id, _project_id)
        self.assertIsNone(output)
        image_service.download.assert_called_once_with(ctxt, image_id,
                                                       mock_open.return_value)
        mock_open.assert_called_once_with(path, 'wb')
        mock_fileutils.remove_path_on_error.assert_called_once_with(path)
        (mock_fileutils.remove_path_on_error.return_value.__enter__
            .assert_called_once_with())
        (mock_fileutils.remove_path_on_error.return_value.__exit__
            .assert_called_once_with(None, None, None))


class TestVerifyImage(test.TestCase):
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.fileutils')
    @mock.patch('cinder.image.image_utils.fetch')
    def test_defaults(self, mock_fetch, mock_fileutils, mock_info):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        mock_data = mock_info.return_value
        mock_data.file_format = 'test_format'
        mock_data.backing_file = None

        output = image_utils.fetch_verify_image(ctxt, image_service,
                                                image_id, dest)
        self.assertIsNone(output)
        mock_fetch.assert_called_once_with(ctxt, image_service, image_id,
                                           dest, None, None)
        mock_info.assert_called_once_with(dest, run_as_root=True)
        mock_fileutils.remove_path_on_error.assert_called_once_with(dest)
        (mock_fileutils.remove_path_on_error.return_value.__enter__
            .assert_called_once_with())
        (mock_fileutils.remove_path_on_error.return_value.__exit__
            .assert_called_once_with(None, None, None))

    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.fileutils')
    @mock.patch('cinder.image.image_utils.fetch')
    def test_kwargs(self, mock_fetch, mock_fileutils, mock_info):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        user_id = mock.sentinel.user_id
        project_id = mock.sentinel.project_id
        size = 2
        run_as_root = mock.sentinel.run_as_root
        mock_data = mock_info.return_value
        mock_data.file_format = 'test_format'
        mock_data.backing_file = None
        mock_data.virtual_size = 1

        output = image_utils.fetch_verify_image(
            ctxt, image_service, image_id, dest, user_id=user_id,
            project_id=project_id, size=size, run_as_root=run_as_root)
        self.assertIsNone(output)
        mock_fetch.assert_called_once_with(ctxt, image_service, image_id,
                                           dest, None, None)
        mock_info.assert_called_once_with(dest, run_as_root=run_as_root)
        mock_fileutils.remove_path_on_error.assert_called_once_with(dest)
        (mock_fileutils.remove_path_on_error.return_value.__enter__
            .assert_called_once_with())
        (mock_fileutils.remove_path_on_error.return_value.__exit__
            .assert_called_once_with(None, None, None))

    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.fileutils')
    @mock.patch('cinder.image.image_utils.fetch')
    def test_format_error(self, mock_fetch, mock_fileutils, mock_info):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        mock_data = mock_info.return_value
        mock_data.file_format = None
        mock_data.backing_file = None

        self.assertRaises(exception.ImageUnacceptable,
                          image_utils.fetch_verify_image,
                          ctxt, image_service, image_id, dest)

    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.fileutils')
    @mock.patch('cinder.image.image_utils.fetch')
    def test_backing_file_error(self, mock_fetch, mock_fileutils, mock_info):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        mock_data = mock_info.return_value
        mock_data.file_format = 'test_format'
        mock_data.backing_file = 'test_backing_file'

        self.assertRaises(exception.ImageUnacceptable,
                          image_utils.fetch_verify_image,
                          ctxt, image_service, image_id, dest)

    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.fileutils')
    @mock.patch('cinder.image.image_utils.fetch')
    def test_size_error(self, mock_fetch, mock_fileutils, mock_info):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        size = 1
        mock_data = mock_info.return_value
        mock_data.file_format = 'test_format'
        mock_data.backing_file = None
        mock_data.virtual_size = 2

        self.assertRaises(exception.ImageUnacceptable,
                          image_utils.fetch_verify_image,
                          ctxt, image_service, image_id, dest, size=size)


class TestTemporaryDir(test.TestCase):
    @mock.patch('cinder.image.image_utils.CONF')
    @mock.patch('os.makedirs')
    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('cinder.image.image_utils.utils.tempdir')
    def test_conv_dir_exists(self, mock_tempdir, mock_exists, mock_make,
                             mock_conf):
        mock_conf.image_conversion_dir = mock.sentinel.conv_dir

        output = image_utils.temporary_dir()

        self.assertFalse(mock_make.called)
        mock_tempdir.assert_called_once_with(dir=mock.sentinel.conv_dir)
        self.assertEqual(output, mock_tempdir.return_value)

    @mock.patch('cinder.image.image_utils.CONF')
    @mock.patch('os.makedirs')
    @mock.patch('os.path.exists', return_value=False)
    @mock.patch('cinder.image.image_utils.utils.tempdir')
    def test_create_conv_dir(self, mock_tempdir, mock_exists, mock_make,
                             mock_conf):
        mock_conf.image_conversion_dir = mock.sentinel.conv_dir

        output = image_utils.temporary_dir()

        mock_make.assert_called_once_with(mock.sentinel.conv_dir)
        mock_tempdir.assert_called_once_with(dir=mock.sentinel.conv_dir)
        self.assertEqual(output, mock_tempdir.return_value)

    @mock.patch('cinder.image.image_utils.CONF')
    @mock.patch('os.makedirs')
    @mock.patch('os.path.exists', return_value=False)
    @mock.patch('cinder.image.image_utils.utils.tempdir')
    def test_no_conv_dir(self, mock_tempdir, mock_exists, mock_make,
                         mock_conf):
        mock_conf.image_conversion_dir = None

        output = image_utils.temporary_dir()

        self.assertFalse(mock_make.called)
        mock_tempdir.assert_called_once_with(dir=None)
        self.assertEqual(output, mock_tempdir.return_value)


class TestUploadVolume(test.TestCase):
    @mock.patch('cinder.image.image_utils.CONF')
    @mock.patch('six.moves.builtins.open')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.os')
    def test_diff_format(self, mock_os, mock_temp, mock_convert, mock_info,
                         mock_open, mock_conf):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_meta = {'id': 'test_id',
                      'disk_format': mock.sentinel.disk_format}
        volume_path = mock.sentinel.volume_path
        mock_os.name = 'posix'
        data = mock_info.return_value
        data.file_format = mock.sentinel.disk_format
        data.backing_file = None
        temp_file = mock_temp.return_value.__enter__.return_value

        output = image_utils.upload_volume(ctxt, image_service, image_meta,
                                           volume_path)

        self.assertIsNone(output)
        mock_convert.assert_called_once_with(volume_path,
                                             temp_file,
                                             mock.sentinel.disk_format,
                                             run_as_root=True)
        mock_info.assert_called_with(temp_file, run_as_root=True)
        self.assertEqual(2, mock_info.call_count)
        mock_open.assert_called_once_with(temp_file, 'rb')
        image_service.update.assert_called_once_with(
            ctxt, image_meta['id'], {},
            mock_open.return_value.__enter__.return_value)

    @mock.patch('cinder.image.image_utils.utils.temporary_chown')
    @mock.patch('cinder.image.image_utils.CONF')
    @mock.patch('six.moves.builtins.open')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.os')
    def test_same_format(self, mock_os, mock_temp, mock_convert, mock_info,
                         mock_open, mock_conf, mock_chown):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_meta = {'id': 'test_id',
                      'disk_format': 'raw'}
        volume_path = mock.sentinel.volume_path
        mock_os.name = 'posix'
        mock_os.access.return_value = False

        output = image_utils.upload_volume(ctxt, image_service, image_meta,
                                           volume_path)

        self.assertIsNone(output)
        self.assertFalse(mock_convert.called)
        self.assertFalse(mock_info.called)
        mock_chown.assert_called_once_with(volume_path)
        mock_open.assert_called_once_with(volume_path)
        image_service.update.assert_called_once_with(
            ctxt, image_meta['id'], {},
            mock_open.return_value.__enter__.return_value)

    @mock.patch('cinder.image.image_utils.utils.temporary_chown')
    @mock.patch('cinder.image.image_utils.CONF')
    @mock.patch('six.moves.builtins.open')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.os')
    def test_same_format_on_nt(self, mock_os, mock_temp, mock_convert,
                               mock_info, mock_open, mock_conf, mock_chown):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_meta = {'id': 'test_id',
                      'disk_format': 'raw'}
        volume_path = mock.sentinel.volume_path
        mock_os.name = 'nt'
        mock_os.access.return_value = False

        output = image_utils.upload_volume(ctxt, image_service, image_meta,
                                           volume_path)

        self.assertIsNone(output)
        self.assertFalse(mock_convert.called)
        self.assertFalse(mock_info.called)
        mock_open.assert_called_once_with(volume_path, 'rb')
        image_service.update.assert_called_once_with(
            ctxt, image_meta['id'], {},
            mock_open.return_value.__enter__.return_value)

    @mock.patch('cinder.image.image_utils.CONF')
    @mock.patch('six.moves.builtins.open')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.os')
    def test_convert_error(self, mock_os, mock_temp, mock_convert, mock_info,
                           mock_open, mock_conf):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_meta = {'id': 'test_id',
                      'disk_format': mock.sentinel.disk_format}
        volume_path = mock.sentinel.volume_path
        mock_os.name = 'posix'
        data = mock_info.return_value
        data.file_format = mock.sentinel.other_disk_format
        data.backing_file = None
        temp_file = mock_temp.return_value.__enter__.return_value

        self.assertRaises(exception.ImageUnacceptable,
                          image_utils.upload_volume,
                          ctxt, image_service, image_meta, volume_path)
        mock_convert.assert_called_once_with(volume_path,
                                             temp_file,
                                             mock.sentinel.disk_format,
                                             run_as_root=True)
        mock_info.assert_called_with(temp_file, run_as_root=True)
        self.assertEqual(2, mock_info.call_count)
        self.assertFalse(image_service.update.called)


class TestFetchToVhd(test.TestCase):
    @mock.patch('cinder.image.image_utils.fetch_to_volume_format')
    def test_defaults(self, mock_fetch_to):
        ctxt = mock.sentinel.context
        image_service = mock.sentinel.image_service
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        blocksize = mock.sentinel.blocksize

        output = image_utils.fetch_to_vhd(ctxt, image_service, image_id,
                                          dest, blocksize)
        self.assertIsNone(output)
        mock_fetch_to.assert_called_once_with(ctxt, image_service, image_id,
                                              dest, 'vpc', blocksize, None,
                                              None, run_as_root=True)

    @mock.patch('cinder.image.image_utils.fetch_to_volume_format')
    def test_kwargs(self, mock_fetch_to):
        ctxt = mock.sentinel.context
        image_service = mock.sentinel.image_service
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        blocksize = mock.sentinel.blocksize
        user_id = mock.sentinel.user_id
        project_id = mock.sentinel.project_id
        run_as_root = mock.sentinel.run_as_root

        output = image_utils.fetch_to_vhd(ctxt, image_service, image_id,
                                          dest, blocksize, user_id=user_id,
                                          project_id=project_id,
                                          run_as_root=run_as_root)
        self.assertIsNone(output)
        mock_fetch_to.assert_called_once_with(ctxt, image_service, image_id,
                                              dest, 'vpc', blocksize, user_id,
                                              project_id,
                                              run_as_root=run_as_root)


class TestFetchToRaw(test.TestCase):
    @mock.patch('cinder.image.image_utils.fetch_to_volume_format')
    def test_defaults(self, mock_fetch_to):
        ctxt = mock.sentinel.context
        image_service = mock.sentinel.image_service
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        blocksize = mock.sentinel.blocksize

        output = image_utils.fetch_to_raw(ctxt, image_service, image_id,
                                          dest, blocksize)
        self.assertIsNone(output)
        mock_fetch_to.assert_called_once_with(ctxt, image_service, image_id,
                                              dest, 'raw', blocksize, None,
                                              None, None, run_as_root=True)

    @mock.patch('cinder.image.image_utils.fetch_to_volume_format')
    def test_kwargs(self, mock_fetch_to):
        ctxt = mock.sentinel.context
        image_service = mock.sentinel.image_service
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        blocksize = mock.sentinel.blocksize
        user_id = mock.sentinel.user_id
        project_id = mock.sentinel.project_id
        size = mock.sentinel.size
        run_as_root = mock.sentinel.run_as_root

        output = image_utils.fetch_to_raw(ctxt, image_service, image_id,
                                          dest, blocksize, user_id=user_id,
                                          project_id=project_id, size=size,
                                          run_as_root=run_as_root)
        self.assertIsNone(output)
        mock_fetch_to.assert_called_once_with(ctxt, image_service, image_id,
                                              dest, 'raw', blocksize, user_id,
                                              project_id, size,
                                              run_as_root=run_as_root)


class TestFetchToVolumeFormat(test.TestCase):
    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.volume_utils.copy_volume')
    @mock.patch(
        'cinder.image.image_utils.replace_xenserver_image_with_coalesced_vhd')
    @mock.patch('cinder.image.image_utils.is_xenserver_image',
                return_value=False)
    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.CONF')
    def test_defaults(self, mock_conf, mock_temp, mock_info, mock_fetch,
                      mock_is_xen, mock_repl_xen, mock_copy, mock_convert):
        ctxt = mock.sentinel.context
        ctxt.user_id = mock.sentinel.user_id
        image_service = mock.Mock(temp_images=None)
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        volume_format = mock.sentinel.volume_format
        blocksize = mock.sentinel.blocksize

        data = mock_info.return_value
        data.file_format = volume_format
        data.backing_file = None
        data.virtual_size = 1234
        tmp = mock_temp.return_value.__enter__.return_value

        output = image_utils.fetch_to_volume_format(ctxt, image_service,
                                                    image_id, dest,
                                                    volume_format, blocksize)

        self.assertIsNone(output)
        image_service.show.assert_called_once_with(ctxt, image_id)
        mock_temp.assert_called_once_with()
        mock_info.assert_has_calls([
            mock.call(tmp, run_as_root=True),
            mock.call(tmp, run_as_root=True),
            mock.call(dest, run_as_root=True)])
        mock_fetch.assert_called_once_with(ctxt, image_service, image_id,
                                           tmp, None, None)
        self.assertFalse(mock_repl_xen.called)
        self.assertFalse(mock_copy.called)
        mock_convert.assert_called_once_with(tmp, dest, volume_format,
                                             run_as_root=True)

    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.volume_utils.copy_volume')
    @mock.patch(
        'cinder.image.image_utils.replace_xenserver_image_with_coalesced_vhd')
    @mock.patch('cinder.image.image_utils.is_xenserver_image',
                return_value=False)
    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.CONF')
    def test_kwargs(self, mock_conf, mock_temp, mock_info, mock_fetch,
                    mock_is_xen, mock_repl_xen, mock_copy, mock_convert):
        ctxt = mock.sentinel.context
        image_service = mock.Mock(temp_images=None)
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        volume_format = mock.sentinel.volume_format
        blocksize = mock.sentinel.blocksize
        ctxt.user_id = user_id = mock.sentinel.user_id
        project_id = mock.sentinel.project_id
        size = 4321
        run_as_root = mock.sentinel.run_as_root

        data = mock_info.return_value
        data.file_format = volume_format
        data.backing_file = None
        data.virtual_size = 1234
        tmp = mock_temp.return_value.__enter__.return_value

        output = image_utils.fetch_to_volume_format(
            ctxt, image_service, image_id, dest, volume_format, blocksize,
            user_id=user_id, project_id=project_id, size=size,
            run_as_root=run_as_root)

        self.assertIsNone(output)
        image_service.show.assert_called_once_with(ctxt, image_id)
        mock_temp.assert_called_once_with()
        mock_info.assert_has_calls([
            mock.call(tmp, run_as_root=run_as_root),
            mock.call(tmp, run_as_root=run_as_root),
            mock.call(dest, run_as_root=run_as_root)])
        mock_fetch.assert_called_once_with(ctxt, image_service, image_id,
                                           tmp, user_id, project_id)
        self.assertFalse(mock_repl_xen.called)
        self.assertFalse(mock_copy.called)
        mock_convert.assert_called_once_with(tmp, dest, volume_format,
                                             run_as_root=run_as_root)

    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.volume_utils.copy_volume')
    @mock.patch(
        'cinder.image.image_utils.replace_xenserver_image_with_coalesced_vhd')
    @mock.patch('cinder.image.image_utils.is_xenserver_image',
                return_value=False)
    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.CONF')
    def test_temporary_images(self, mock_conf, mock_temp, mock_info,
                              mock_fetch, mock_is_xen, mock_repl_xen,
                              mock_copy, mock_convert):
        ctxt = mock.sentinel.context
        ctxt.user_id = mock.sentinel.user_id
        image_service = mock.Mock(temp_images=None)
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        volume_format = mock.sentinel.volume_format
        blocksize = mock.sentinel.blocksize

        data = mock_info.return_value
        data.file_format = volume_format
        data.backing_file = None
        data.virtual_size = 1234
        tmp = mock.sentinel.tmp
        dummy = mock.sentinel.dummy
        mock_temp.return_value.__enter__.side_effect = [tmp, dummy]

        with image_utils.TemporaryImages.fetch(image_service, ctxt,
                                               image_id) as tmp_img:
            self.assertEqual(tmp_img, tmp)
            output = image_utils.fetch_to_volume_format(ctxt, image_service,
                                                        image_id, dest,
                                                        volume_format,
                                                        blocksize)

        self.assertIsNone(output)
        image_service.show.assert_called_once_with(ctxt, image_id)
        self.assertEqual(2, mock_temp.call_count)
        mock_info.assert_has_calls([
            mock.call(tmp, run_as_root=True),
            mock.call(dummy, run_as_root=True),
            mock.call(tmp, run_as_root=True),
            mock.call(dest, run_as_root=True)])
        mock_fetch.assert_called_once_with(ctxt, image_service, image_id,
                                           tmp, None, None)
        self.assertFalse(mock_repl_xen.called)
        self.assertFalse(mock_copy.called)
        mock_convert.assert_called_once_with(tmp, dest, volume_format,
                                             run_as_root=True)

    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.volume_utils.copy_volume')
    @mock.patch(
        'cinder.image.image_utils.replace_xenserver_image_with_coalesced_vhd')
    @mock.patch('cinder.image.image_utils.is_xenserver_image',
                return_value=False)
    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info',
                side_effect=processutils.ProcessExecutionError)
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.CONF')
    def test_no_qemu_img_and_is_raw(self, mock_conf, mock_temp, mock_info,
                                    mock_fetch, mock_is_xen, mock_repl_xen,
                                    mock_copy, mock_convert):
        ctxt = mock.sentinel.context
        image_service = mock.Mock(temp_images=None)
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        volume_format = mock.sentinel.volume_format
        blocksize = mock.sentinel.blocksize
        ctxt.user_id = user_id = mock.sentinel.user_id
        project_id = mock.sentinel.project_id
        size = 4321
        run_as_root = mock.sentinel.run_as_root

        tmp = mock_temp.return_value.__enter__.return_value
        image_service.show.return_value = {'disk_format': 'raw',
                                           'size': 41126400}
        image_size_m = math.ceil(41126400 / units.Mi)

        output = image_utils.fetch_to_volume_format(
            ctxt, image_service, image_id, dest, volume_format, blocksize,
            user_id=user_id, project_id=project_id, size=size,
            run_as_root=run_as_root)

        self.assertIsNone(output)
        image_service.show.assert_called_once_with(ctxt, image_id)
        mock_temp.assert_called_once_with()
        mock_info.assert_called_once_with(tmp, run_as_root=run_as_root)
        mock_fetch.assert_called_once_with(ctxt, image_service, image_id,
                                           tmp, user_id, project_id)
        self.assertFalse(mock_repl_xen.called)
        mock_copy.assert_called_once_with(tmp, dest, image_size_m,
                                          blocksize)
        self.assertFalse(mock_convert.called)

    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.volume_utils.copy_volume')
    @mock.patch(
        'cinder.image.image_utils.replace_xenserver_image_with_coalesced_vhd')
    @mock.patch('cinder.image.image_utils.is_xenserver_image',
                return_value=False)
    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info',
                side_effect=processutils.ProcessExecutionError)
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.CONF')
    def test_no_qemu_img_not_raw(self, mock_conf, mock_temp, mock_info,
                                 mock_fetch, mock_is_xen, mock_repl_xen,
                                 mock_copy, mock_convert):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        volume_format = mock.sentinel.volume_format
        blocksize = mock.sentinel.blocksize
        user_id = mock.sentinel.user_id
        project_id = mock.sentinel.project_id
        size = 4321
        run_as_root = mock.sentinel.run_as_root

        tmp = mock_temp.return_value.__enter__.return_value
        image_service.show.return_value = {'disk_format': 'not_raw'}

        self.assertRaises(
            exception.ImageUnacceptable,
            image_utils.fetch_to_volume_format,
            ctxt, image_service, image_id, dest, volume_format, blocksize,
            user_id=user_id, project_id=project_id, size=size,
            run_as_root=run_as_root)

        image_service.show.assert_called_once_with(ctxt, image_id)
        mock_temp.assert_called_once_with()
        mock_info.assert_called_once_with(tmp, run_as_root=run_as_root)
        self.assertFalse(mock_fetch.called)
        self.assertFalse(mock_repl_xen.called)
        self.assertFalse(mock_copy.called)
        self.assertFalse(mock_convert.called)

    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.volume_utils.copy_volume')
    @mock.patch(
        'cinder.image.image_utils.replace_xenserver_image_with_coalesced_vhd')
    @mock.patch('cinder.image.image_utils.is_xenserver_image',
                return_value=False)
    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info',
                side_effect=processutils.ProcessExecutionError)
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.CONF')
    def test_no_qemu_img_no_metadata(self, mock_conf, mock_temp, mock_info,
                                     mock_fetch, mock_is_xen, mock_repl_xen,
                                     mock_copy, mock_convert):
        ctxt = mock.sentinel.context
        image_service = mock.Mock(temp_images=None)
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        volume_format = mock.sentinel.volume_format
        blocksize = mock.sentinel.blocksize
        ctxt.user_id = user_id = mock.sentinel.user_id
        project_id = mock.sentinel.project_id
        size = 4321
        run_as_root = mock.sentinel.run_as_root

        tmp = mock_temp.return_value.__enter__.return_value
        image_service.show.return_value = None

        self.assertRaises(
            exception.ImageUnacceptable,
            image_utils.fetch_to_volume_format,
            ctxt, image_service, image_id, dest, volume_format, blocksize,
            user_id=user_id, project_id=project_id, size=size,
            run_as_root=run_as_root)

        image_service.show.assert_called_once_with(ctxt, image_id)
        mock_temp.assert_called_once_with()
        mock_info.assert_called_once_with(tmp, run_as_root=run_as_root)
        self.assertFalse(mock_fetch.called)
        self.assertFalse(mock_repl_xen.called)
        self.assertFalse(mock_copy.called)
        self.assertFalse(mock_convert.called)

    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.volume_utils.copy_volume')
    @mock.patch(
        'cinder.image.image_utils.replace_xenserver_image_with_coalesced_vhd')
    @mock.patch('cinder.image.image_utils.is_xenserver_image',
                return_value=False)
    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.CONF')
    def test_size_error(self, mock_conf, mock_temp, mock_info, mock_fetch,
                        mock_is_xen, mock_repl_xen, mock_copy, mock_convert):
        ctxt = mock.sentinel.context
        image_service = mock.Mock(temp_images=None)
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        volume_format = mock.sentinel.volume_format
        blocksize = mock.sentinel.blocksize
        ctxt.user_id = user_id = mock.sentinel.user_id
        project_id = mock.sentinel.project_id
        size = 1234
        run_as_root = mock.sentinel.run_as_root

        data = mock_info.return_value
        data.file_format = volume_format
        data.backing_file = None
        data.virtual_size = 4321 * 1024 ** 3
        tmp = mock_temp.return_value.__enter__.return_value

        self.assertRaises(
            exception.ImageUnacceptable,
            image_utils.fetch_to_volume_format,
            ctxt, image_service, image_id, dest, volume_format, blocksize,
            user_id=user_id, project_id=project_id, size=size,
            run_as_root=run_as_root)

        image_service.show.assert_called_once_with(ctxt, image_id)
        mock_temp.assert_called_once_with()
        mock_info.assert_has_calls([
            mock.call(tmp, run_as_root=run_as_root),
            mock.call(tmp, run_as_root=run_as_root)])
        mock_fetch.assert_called_once_with(ctxt, image_service, image_id,
                                           tmp, user_id, project_id)
        self.assertFalse(mock_repl_xen.called)
        self.assertFalse(mock_copy.called)
        self.assertFalse(mock_convert.called)

    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.volume_utils.copy_volume')
    @mock.patch(
        'cinder.image.image_utils.replace_xenserver_image_with_coalesced_vhd')
    @mock.patch('cinder.image.image_utils.is_xenserver_image',
                return_value=False)
    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.CONF')
    def test_qemu_img_parse_error(self, mock_conf, mock_temp, mock_info,
                                  mock_fetch, mock_is_xen, mock_repl_xen,
                                  mock_copy, mock_convert):
        ctxt = mock.sentinel.context
        image_service = mock.Mock(temp_images=None)
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        volume_format = mock.sentinel.volume_format
        blocksize = mock.sentinel.blocksize
        ctxt.user_id = user_id = mock.sentinel.user_id
        project_id = mock.sentinel.project_id
        size = 4321
        run_as_root = mock.sentinel.run_as_root

        data = mock_info.return_value
        data.file_format = None
        data.backing_file = None
        data.virtual_size = 1234
        tmp = mock_temp.return_value.__enter__.return_value

        self.assertRaises(
            exception.ImageUnacceptable,
            image_utils.fetch_to_volume_format,
            ctxt, image_service, image_id, dest, volume_format, blocksize,
            user_id=user_id, project_id=project_id, size=size,
            run_as_root=run_as_root)

        image_service.show.assert_called_once_with(ctxt, image_id)
        mock_temp.assert_called_once_with()
        mock_info.assert_has_calls([
            mock.call(tmp, run_as_root=run_as_root),
            mock.call(tmp, run_as_root=run_as_root)])
        mock_fetch.assert_called_once_with(ctxt, image_service, image_id,
                                           tmp, user_id, project_id)
        self.assertFalse(mock_repl_xen.called)
        self.assertFalse(mock_copy.called)
        self.assertFalse(mock_convert.called)

    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.volume_utils.copy_volume')
    @mock.patch(
        'cinder.image.image_utils.replace_xenserver_image_with_coalesced_vhd')
    @mock.patch('cinder.image.image_utils.is_xenserver_image',
                return_value=False)
    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.CONF')
    def test_backing_file_error(self, mock_conf, mock_temp, mock_info,
                                mock_fetch, mock_is_xen, mock_repl_xen,
                                mock_copy, mock_convert):
        ctxt = mock.sentinel.context
        image_service = mock.Mock(temp_images=None)
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        volume_format = mock.sentinel.volume_format
        blocksize = mock.sentinel.blocksize
        ctxt.user_id = user_id = mock.sentinel.user_id
        project_id = mock.sentinel.project_id
        size = 4321
        run_as_root = mock.sentinel.run_as_root

        data = mock_info.return_value
        data.file_format = volume_format
        data.backing_file = mock.sentinel.backing_file
        data.virtual_size = 1234
        tmp = mock_temp.return_value.__enter__.return_value

        self.assertRaises(
            exception.ImageUnacceptable,
            image_utils.fetch_to_volume_format,
            ctxt, image_service, image_id, dest, volume_format, blocksize,
            user_id=user_id, project_id=project_id, size=size,
            run_as_root=run_as_root)

        image_service.show.assert_called_once_with(ctxt, image_id)
        mock_temp.assert_called_once_with()
        mock_info.assert_has_calls([
            mock.call(tmp, run_as_root=run_as_root),
            mock.call(tmp, run_as_root=run_as_root)])
        mock_fetch.assert_called_once_with(ctxt, image_service, image_id,
                                           tmp, user_id, project_id)
        self.assertFalse(mock_repl_xen.called)
        self.assertFalse(mock_copy.called)
        self.assertFalse(mock_convert.called)

    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.volume_utils.copy_volume')
    @mock.patch(
        'cinder.image.image_utils.replace_xenserver_image_with_coalesced_vhd')
    @mock.patch('cinder.image.image_utils.is_xenserver_image',
                return_value=False)
    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.CONF')
    def _test_format_name_mismatch(self, mock_conf, mock_temp, mock_info,
                                   mock_fetch, mock_is_xen, mock_repl_xen,
                                   mock_copy, mock_convert,
                                   legacy_format_name=False):
        ctxt = mock.sentinel.context
        image_service = mock.Mock(temp_images=None)
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        volume_format = 'vhd'
        blocksize = mock.sentinel.blocksize
        ctxt.user_id = user_id = mock.sentinel.user_id
        project_id = mock.sentinel.project_id
        size = 4321
        run_as_root = mock.sentinel.run_as_root

        data = mock_info.return_value
        data.file_format = 'vpc' if legacy_format_name else 'raw'
        data.backing_file = None
        data.virtual_size = 1234
        tmp = mock_temp.return_value.__enter__.return_value

        if legacy_format_name:
            image_utils.fetch_to_volume_format(
                ctxt, image_service, image_id, dest, volume_format, blocksize,
                user_id=user_id, project_id=project_id, size=size,
                run_as_root=run_as_root)
        else:
            self.assertRaises(
                exception.ImageUnacceptable,
                image_utils.fetch_to_volume_format,
                ctxt, image_service, image_id, dest, volume_format, blocksize,
                user_id=user_id, project_id=project_id, size=size,
                run_as_root=run_as_root)

        image_service.show.assert_called_once_with(ctxt, image_id)
        mock_temp.assert_called_once_with()
        mock_info.assert_has_calls([
            mock.call(tmp, run_as_root=run_as_root),
            mock.call(tmp, run_as_root=run_as_root),
            mock.call(dest, run_as_root=run_as_root)])
        mock_fetch.assert_called_once_with(ctxt, image_service, image_id,
                                           tmp, user_id, project_id)
        self.assertFalse(mock_repl_xen.called)
        self.assertFalse(mock_copy.called)
        mock_convert.assert_called_once_with(tmp, dest, volume_format,
                                             run_as_root=run_as_root)

    def test_format_mismatch(self):
        self._test_format_name_mismatch()

    def test_format_name_mismatch_same_format(self):
        # Make sure no exception is raised because of qemu-img still using
        # the legacy 'vpc' format name if 'vhd' is requested.
        self._test_format_name_mismatch(legacy_format_name=True)

    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.volume_utils.copy_volume')
    @mock.patch(
        'cinder.image.image_utils.replace_xenserver_image_with_coalesced_vhd')
    @mock.patch('cinder.image.image_utils.is_xenserver_image',
                return_value=True)
    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.CONF')
    def test_xenserver_to_vhd(self, mock_conf, mock_temp, mock_info,
                              mock_fetch, mock_is_xen, mock_repl_xen,
                              mock_copy, mock_convert):
        ctxt = mock.sentinel.context
        image_service = mock.Mock(temp_images=None)
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        volume_format = mock.sentinel.volume_format
        blocksize = mock.sentinel.blocksize
        ctxt.user_id = user_id = mock.sentinel.user_id
        project_id = mock.sentinel.project_id
        size = 4321
        run_as_root = mock.sentinel.run_as_root

        data = mock_info.return_value
        data.file_format = volume_format
        data.backing_file = None
        data.virtual_size = 1234
        tmp = mock_temp.return_value.__enter__.return_value

        output = image_utils.fetch_to_volume_format(
            ctxt, image_service, image_id, dest, volume_format, blocksize,
            user_id=user_id, project_id=project_id, size=size,
            run_as_root=run_as_root)

        self.assertIsNone(output)
        image_service.show.assert_called_once_with(ctxt, image_id)
        mock_temp.assert_called_once_with()
        mock_info.assert_has_calls([
            mock.call(tmp, run_as_root=run_as_root),
            mock.call(tmp, run_as_root=run_as_root),
            mock.call(dest, run_as_root=run_as_root)])
        mock_fetch.assert_called_once_with(ctxt, image_service, image_id,
                                           tmp, user_id, project_id)
        mock_repl_xen.assert_called_once_with(tmp)
        self.assertFalse(mock_copy.called)
        mock_convert.assert_called_once_with(tmp, dest, volume_format,
                                             run_as_root=run_as_root)


class TestXenserverUtils(test.TestCase):
    @mock.patch('cinder.image.image_utils.is_xenserver_format')
    def test_is_xenserver_image(self, mock_format):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_id = mock.sentinel.image_id

        output = image_utils.is_xenserver_image(ctxt, image_service, image_id)

        image_service.show.assert_called_once_with(ctxt, image_id)
        mock_format.assert_called_once_with(image_service.show.return_value)
        self.assertEqual(mock_format.return_value, output)

    def test_is_xenserver_format(self):
        image_meta1 = {'disk_format': 'vhd', 'container_format': 'ovf'}
        self.assertTrue(image_utils.is_xenserver_format(image_meta1))

        image_meta2 = {'disk_format': 'test_disk_format',
                       'container_format': 'test_cont_format'}
        self.assertFalse(image_utils.is_xenserver_format(image_meta2))

    @mock.patch('cinder.image.image_utils.utils.execute')
    def test_extract_targz(self, mock_exec):
        name = mock.sentinel.archive_name
        target = mock.sentinel.target

        output = image_utils.extract_targz(name, target)

        mock_exec.assert_called_once_with('tar', '-xzf', name, '-C', target)
        self.assertIsNone(output)


class TestVhdUtils(test.TestCase):
    @mock.patch('cinder.image.image_utils.utils.execute')
    def test_set_vhd_parent(self, mock_exec):
        vhd_path = mock.sentinel.vhd_path
        parentpath = mock.sentinel.parentpath

        output = image_utils.set_vhd_parent(vhd_path, parentpath)

        mock_exec.assert_called_once_with('vhd-util', 'modify', '-n', vhd_path,
                                          '-p', parentpath)
        self.assertIsNone(output)

    @mock.patch('cinder.image.image_utils.set_vhd_parent')
    def test_fix_vhd_chain(self, mock_set_parent):
        vhd_chain = (mock.sentinel.first,
                     mock.sentinel.second,
                     mock.sentinel.third,
                     mock.sentinel.fourth,
                     mock.sentinel.fifth)

        output = image_utils.fix_vhd_chain(vhd_chain)

        self.assertIsNone(output)
        mock_set_parent.assert_has_calls([
            mock.call(mock.sentinel.first, mock.sentinel.second),
            mock.call(mock.sentinel.second, mock.sentinel.third),
            mock.call(mock.sentinel.third, mock.sentinel.fourth),
            mock.call(mock.sentinel.fourth, mock.sentinel.fifth)])

    @mock.patch('cinder.image.image_utils.utils.execute',
                return_value=(98765.43210, mock.sentinel.error))
    def test_get_vhd_size(self, mock_exec):
        vhd_path = mock.sentinel.vhd_path

        output = image_utils.get_vhd_size(vhd_path)

        mock_exec.assert_called_once_with('vhd-util', 'query', '-n', vhd_path,
                                          '-v')
        self.assertEqual(98765, output)

    @mock.patch('cinder.image.image_utils.utils.execute')
    def test_resize_vhd(self, mock_exec):
        vhd_path = mock.sentinel.vhd_path
        size = 387549349
        journal = mock.sentinel.journal

        output = image_utils.resize_vhd(vhd_path, size, journal)

        self.assertIsNone(output)
        mock_exec.assert_called_once_with('vhd-util', 'resize', '-n', vhd_path,
                                          '-s', str(size), '-j', journal)

    @mock.patch('cinder.image.image_utils.utils.execute')
    def test_coalesce_vhd(self, mock_exec):
        vhd_path = mock.sentinel.vhd_path

        output = image_utils.coalesce_vhd(vhd_path)

        self.assertIsNone(output)
        mock_exec.assert_called_once_with('vhd-util', 'coalesce', '-n',
                                          vhd_path)

    @mock.patch('cinder.image.image_utils.coalesce_vhd')
    @mock.patch('cinder.image.image_utils.resize_vhd')
    @mock.patch('cinder.image.image_utils.get_vhd_size')
    @mock.patch('cinder.image.image_utils.utils.execute')
    def test_coalesce_chain(self, mock_exec, mock_size, mock_resize,
                            mock_coal):
        vhd_chain = (mock.sentinel.first,
                     mock.sentinel.second,
                     mock.sentinel.third,
                     mock.sentinel.fourth,
                     mock.sentinel.fifth)

        output = image_utils.coalesce_chain(vhd_chain)

        self.assertEqual(mock.sentinel.fifth, output)
        mock_size.assert_has_calls([
            mock.call(mock.sentinel.first),
            mock.call(mock.sentinel.second),
            mock.call(mock.sentinel.third),
            mock.call(mock.sentinel.fourth)])
        mock_resize.assert_has_calls([
            mock.call(mock.sentinel.second, mock_size.return_value, mock.ANY),
            mock.call(mock.sentinel.third, mock_size.return_value, mock.ANY),
            mock.call(mock.sentinel.fourth, mock_size.return_value, mock.ANY),
            mock.call(mock.sentinel.fifth, mock_size.return_value, mock.ANY)])
        mock_coal.assert_has_calls([
            mock.call(mock.sentinel.first),
            mock.call(mock.sentinel.second),
            mock.call(mock.sentinel.third),
            mock.call(mock.sentinel.fourth)])

    @mock.patch('cinder.image.image_utils.os.path')
    def test_discover_vhd_chain(self, mock_path):
        directory = '/some/test/directory'
        mock_path.join.side_effect = lambda x, y: '/'.join((x, y))
        mock_path.exists.side_effect = (True, True, True, False)

        output = image_utils.discover_vhd_chain(directory)

        expected_output = ['/some/test/directory/0.vhd',
                           '/some/test/directory/1.vhd',
                           '/some/test/directory/2.vhd']
        self.assertEqual(expected_output, output)

    @mock.patch('cinder.image.image_utils.temporary_dir')
    @mock.patch('cinder.image.image_utils.os.rename')
    @mock.patch('cinder.image.image_utils.fileutils.delete_if_exists')
    @mock.patch('cinder.image.image_utils.coalesce_chain')
    @mock.patch('cinder.image.image_utils.fix_vhd_chain')
    @mock.patch('cinder.image.image_utils.discover_vhd_chain')
    @mock.patch('cinder.image.image_utils.extract_targz')
    def test_replace_xenserver_image_with_coalesced_vhd(
            self, mock_targz, mock_discover, mock_fix, mock_coal, mock_delete,
            mock_rename, mock_temp):
        image_file = mock.sentinel.image_file
        tmp = mock_temp.return_value.__enter__.return_value

        output = image_utils.replace_xenserver_image_with_coalesced_vhd(
            image_file)

        self.assertIsNone(output)
        mock_targz.assert_called_once_with(image_file, tmp)
        mock_discover.assert_called_once_with(tmp)
        mock_fix.assert_called_once_with(mock_discover.return_value)
        mock_coal.assert_called_once_with(mock_discover.return_value)
        mock_delete.assert_called_once_with(image_file)
        mock_rename.assert_called_once_with(mock_coal.return_value, image_file)


class TestCreateTemporaryFile(test.TestCase):
    @mock.patch('cinder.image.image_utils.os.close')
    @mock.patch('cinder.image.image_utils.CONF')
    @mock.patch('cinder.image.image_utils.os.path.exists')
    @mock.patch('cinder.image.image_utils.os.makedirs')
    @mock.patch('cinder.image.image_utils.tempfile.mkstemp')
    def test_create_temporary_file_no_dir(self, mock_mkstemp, mock_dirs,
                                          mock_path, mock_conf, mock_close):
        mock_conf.image_conversion_dir = None
        fd = mock.sentinel.file_descriptor
        path = mock.sentinel.absolute_pathname
        mock_mkstemp.return_value = (fd, path)

        output = image_utils.create_temporary_file()

        self.assertEqual(path, output)
        mock_mkstemp.assert_called_once_with(dir=None)
        mock_close.assert_called_once_with(fd)

    @mock.patch('cinder.image.image_utils.os.close')
    @mock.patch('cinder.image.image_utils.CONF')
    @mock.patch('cinder.image.image_utils.os.path.exists', return_value=True)
    @mock.patch('cinder.image.image_utils.os.makedirs')
    @mock.patch('cinder.image.image_utils.tempfile.mkstemp')
    def test_create_temporary_file_with_dir(self, mock_mkstemp, mock_dirs,
                                            mock_path, mock_conf, mock_close):
        conv_dir = mock.sentinel.image_conversion_dir
        mock_conf.image_conversion_dir = conv_dir
        fd = mock.sentinel.file_descriptor
        path = mock.sentinel.absolute_pathname
        mock_mkstemp.return_value = (fd, path)

        output = image_utils.create_temporary_file()

        self.assertEqual(path, output)
        self.assertFalse(mock_dirs.called)
        mock_mkstemp.assert_called_once_with(dir=conv_dir)
        mock_close.assert_called_once_with(fd)

    @mock.patch('cinder.image.image_utils.os.close')
    @mock.patch('cinder.image.image_utils.CONF')
    @mock.patch('cinder.image.image_utils.os.path.exists', return_value=False)
    @mock.patch('cinder.image.image_utils.os.makedirs')
    @mock.patch('cinder.image.image_utils.tempfile.mkstemp')
    def test_create_temporary_file_and_dir(self, mock_mkstemp, mock_dirs,
                                           mock_path, mock_conf, mock_close):
        conv_dir = mock.sentinel.image_conversion_dir
        mock_conf.image_conversion_dir = conv_dir
        fd = mock.sentinel.file_descriptor
        path = mock.sentinel.absolute_pathname
        mock_mkstemp.return_value = (fd, path)

        output = image_utils.create_temporary_file()

        self.assertEqual(path, output)
        mock_dirs.assert_called_once_with(conv_dir)
        mock_mkstemp.assert_called_once_with(dir=conv_dir)
        mock_close.assert_called_once_with(fd)


class TestTemporaryFileContextManager(test.TestCase):
    @mock.patch('cinder.image.image_utils.create_temporary_file',
                return_value=mock.sentinel.temporary_file)
    @mock.patch('cinder.image.image_utils.fileutils.delete_if_exists')
    def test_temporary_file(self, mock_delete, mock_create):
        with image_utils.temporary_file() as tmp_file:
            self.assertEqual(mock.sentinel.temporary_file, tmp_file)
            self.assertFalse(mock_delete.called)
        mock_delete.assert_called_once_with(mock.sentinel.temporary_file)
