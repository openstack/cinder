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

import errno
import math
from unittest import mock

import cryptography
import ddt
from oslo_concurrency import processutils
from oslo_utils import imageutils
from oslo_utils import units

from cinder import exception
from cinder.image import image_utils
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import test
from cinder.volume import throttling


class TestQemuImgInfo(test.TestCase):
    @mock.patch('cinder.privsep.format_inspector.get_format_if_safe')
    @mock.patch('os.name', new='posix')
    @mock.patch('oslo_utils.imageutils.QemuImgInfo')
    @mock.patch('cinder.utils.execute')
    def test_qemu_img_info(self, mock_exec, mock_info, mock_detect):
        mock_out = mock.sentinel.out
        mock_err = mock.sentinel.err
        test_path = mock.sentinel.path
        mock_exec.return_value = (mock_out, mock_err)

        mock_detect.return_value = 'mock_fmt'

        output = image_utils.qemu_img_info(test_path)
        mock_exec.assert_called_once_with(
            'env', 'LC_ALL=C', 'qemu-img', 'info', '-f', 'mock_fmt',
            '--output=json', test_path, run_as_root=True,
            prlimit=image_utils.QEMU_IMG_LIMITS)
        self.assertEqual(mock_info.return_value, output)
        mock_detect.assert_called_once_with(path=test_path,
                                            allow_qcow2_backing_file=False)

    @mock.patch('cinder.privsep.format_inspector.get_format_if_safe')
    @mock.patch('os.name', new='posix')
    @mock.patch('oslo_utils.imageutils.QemuImgInfo')
    @mock.patch('cinder.utils.execute')
    def test_qemu_img_info_qcow2_backing_ok(
            self, mock_exec, mock_info, mock_detect):
        mock_out = mock.sentinel.out
        mock_err = mock.sentinel.err
        test_path = mock.sentinel.path
        mock_exec.return_value = (mock_out, mock_err)

        mock_detect.return_value = 'qcow2'

        output = image_utils.qemu_img_info(
            test_path, allow_qcow2_backing_file=True)
        mock_exec.assert_called_once_with(
            'env', 'LC_ALL=C', 'qemu-img', 'info', '-f', 'qcow2',
            '--output=json', test_path, run_as_root=True,
            prlimit=image_utils.QEMU_IMG_LIMITS)
        self.assertEqual(mock_info.return_value, output)
        mock_detect.assert_called_once_with(path=test_path,
                                            allow_qcow2_backing_file=True)

    @mock.patch('cinder.privsep.format_inspector.get_format_if_safe')
    @mock.patch('os.name', new='posix')
    @mock.patch('oslo_utils.imageutils.QemuImgInfo')
    @mock.patch('cinder.utils.execute')
    def test_qemu_img_info_raw_not_luks(self, mock_exec, mock_info,
                                        mock_detect):
        """To determine if a raw image is luks, we call qemu-img twice."""
        mock_out = mock.sentinel.out
        mock_err = mock.sentinel.err
        test_path = mock.sentinel.path
        mock_exec.side_effect = [(mock_out, mock_err),
                                 # it's not luks, so raise an error
                                 processutils.ProcessExecutionError]

        mock_detect.return_value = 'raw'

        mock_data = mock.Mock()
        mock_data.file_format = 'raw'
        mock_info.return_value = mock_data

        first = mock.call(
            'env', 'LC_ALL=C', 'qemu-img', 'info', '-f', 'raw',
            '--output=json', test_path, run_as_root=True,
            prlimit=image_utils.QEMU_IMG_LIMITS)
        second = mock.call(
            'env', 'LC_ALL=C', 'qemu-img', 'info', '-f', 'luks',
            '--output=json', test_path, run_as_root=True,
            prlimit=image_utils.QEMU_IMG_LIMITS)

        output = image_utils.qemu_img_info(test_path)
        mock_exec.assert_has_calls([first, second])
        mock_info.assert_called_once()
        self.assertEqual(mock_info.return_value, output)
        mock_detect.assert_called_once_with(path=test_path,
                                            allow_qcow2_backing_file=False)

    @mock.patch('cinder.privsep.format_inspector.get_format_if_safe')
    @mock.patch('os.name', new='posix')
    @mock.patch('oslo_utils.imageutils.QemuImgInfo')
    @mock.patch('cinder.utils.execute')
    def test_qemu_img_info_luks(self, mock_exec, mock_info, mock_detect):
        # the format_inspector will identify the image as raw, but
        # we will ask qemu-img for a second opinion, and it say luks
        mock_out = mock.sentinel.out
        mock_err = mock.sentinel.err
        test_path = mock.sentinel.path
        mock_exec.return_value = (mock_out, mock_err)

        mock_detect.return_value = 'raw'

        mock_data1 = mock.Mock(name='first_time')
        mock_data1.file_format = 'raw'
        mock_data2 = mock.Mock(name='second_time')
        mock_data2.file_format = 'luks'
        mock_info.side_effect = [mock_data1, mock_data2]

        first = mock.call(
            'env', 'LC_ALL=C', 'qemu-img', 'info', '-f', 'raw',
            '--output=json', test_path, run_as_root=True,
            prlimit=image_utils.QEMU_IMG_LIMITS)
        second = mock.call(
            'env', 'LC_ALL=C', 'qemu-img', 'info', '-f', 'luks',
            '--output=json', test_path, run_as_root=True,
            prlimit=image_utils.QEMU_IMG_LIMITS)

        output = image_utils.qemu_img_info(test_path)
        mock_exec.assert_has_calls([first, second])
        self.assertEqual(2, mock_info.call_count)
        self.assertEqual(mock_data2, output)
        mock_detect.assert_called_once_with(path=test_path,
                                            allow_qcow2_backing_file=False)

    @mock.patch('cinder.privsep.format_inspector.get_format_if_safe')
    @mock.patch('os.name', new='posix')
    @mock.patch('oslo_utils.imageutils.QemuImgInfo')
    @mock.patch('cinder.utils.execute')
    def test_qemu_img_info_not_root(self, mock_exec, mock_info, mock_detect):
        mock_out = mock.sentinel.out
        mock_err = mock.sentinel.err
        test_path = mock.sentinel.path
        mock_exec.return_value = (mock_out, mock_err)

        mock_detect.return_value = 'mock_fmt'

        output = image_utils.qemu_img_info(test_path,
                                           force_share=False,
                                           run_as_root=False)
        mock_exec.assert_called_once_with(
            'env', 'LC_ALL=C', 'qemu-img', 'info', '-f', 'mock_fmt',
            '--output=json', test_path, run_as_root=False,
            prlimit=image_utils.QEMU_IMG_LIMITS)
        self.assertEqual(mock_info.return_value, output)
        mock_detect.assert_called_once_with(path=test_path,
                                            allow_qcow2_backing_file=False)

    @mock.patch('cinder.privsep.format_inspector.get_format_if_safe')
    @mock.patch('cinder.image.image_utils.os')
    @mock.patch('oslo_utils.imageutils.QemuImgInfo')
    @mock.patch('cinder.utils.execute')
    def test_qemu_img_info_on_nt(self, mock_exec, mock_info, mock_os,
                                 mock_detect):
        mock_out = mock.sentinel.out
        mock_err = mock.sentinel.err
        test_path = mock.sentinel.path
        mock_exec.return_value = (mock_out, mock_err)
        mock_os.name = 'nt'

        mock_detect.return_value = 'mock_fmt'

        output = image_utils.qemu_img_info(test_path)
        mock_exec.assert_called_once_with(
            'qemu-img', 'info', '-f', 'mock_fmt', '--output=json',
            test_path, run_as_root=True, prlimit=image_utils.QEMU_IMG_LIMITS)
        self.assertEqual(mock_info.return_value, output)
        mock_detect.assert_called_once_with(path=test_path,
                                            allow_qcow2_backing_file=False)

    @mock.patch('cinder.privsep.format_inspector.get_format_if_safe')
    @mock.patch('os.name', new='posix')
    @mock.patch('cinder.utils.execute')
    def test_qemu_img_info_malicious(self, mock_exec, mock_detect):
        mock_out = mock.sentinel.out
        mock_err = mock.sentinel.err
        test_path = mock.sentinel.path
        mock_exec.return_value = (mock_out, mock_err)

        mock_detect.return_value = None

        self.assertRaises(exception.Invalid,
                          image_utils.qemu_img_info,
                          test_path,
                          force_share=False,
                          run_as_root=False)
        mock_exec.assert_not_called()
        mock_detect.assert_called_once_with(path=test_path,
                                            allow_qcow2_backing_file=False)

    @mock.patch('cinder.utils.execute')
    def test_get_qemu_img_version(self, mock_exec):
        mock_out = "qemu-img version 2.0.0"
        mock_err = mock.sentinel.err
        mock_exec.return_value = (mock_out, mock_err)

        expected_version = [2, 0, 0]
        version = image_utils.get_qemu_img_version()

        mock_exec.assert_called_once_with('qemu-img', '--version',
                                          check_exit_code=False)
        self.assertEqual(expected_version, version)
        self.assertEqual(1, mock_exec.call_count)

        version = image_utils.get_qemu_img_version()

        # verify that cached value was used instead of calling execute
        self.assertEqual(expected_version, version)
        self.assertEqual(1, mock_exec.call_count)

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


@ddt.ddt
class TestConvertImage(test.TestCase):
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.utils.execute')
    @mock.patch('cinder.utils.is_blk_device', return_value=True)
    def test_defaults_block_dev_with_size_info(self, mock_isblk,
                                               mock_exec, mock_info):
        source = mock.sentinel.source
        dest = mock.sentinel.dest
        out_format = mock.sentinel.out_format
        mock_info.return_value.virtual_size = 1048576
        throttle = throttling.Throttle(prefix=['cgcmd'])

        with mock.patch('cinder.volume.volume_utils.check_for_odirect_support',
                        return_value=True):
            output = image_utils.convert_image(source, dest, out_format,
                                               throttle=throttle)

            self.assertIsNone(output)
            mock_exec.assert_called_once_with('cgcmd', 'qemu-img', 'convert',
                                              '-O', out_format, '-t', 'none',
                                              source, dest, run_as_root=True)

        mock_exec.reset_mock()

        with mock.patch('cinder.volume.volume_utils.check_for_odirect_support',
                        return_value=False):
            output = image_utils.convert_image(source, dest, out_format)

            self.assertIsNone(output)
            mock_exec.assert_called_once_with('qemu-img', 'convert',
                                              '-O', out_format, source, dest,
                                              run_as_root=True)

    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.utils.execute')
    @mock.patch('cinder.utils.is_blk_device', return_value=True)
    def test_defaults_block_dev_without_size_info(self, mock_isblk,
                                                  mock_exec,
                                                  mock_info):
        source = mock.sentinel.source
        dest = mock.sentinel.dest
        out_format = mock.sentinel.out_format
        mock_info.return_value.file_format = 'qcow2'
        mock_info.return_value.virtual_size = 1048576
        mock_info.return_value.format_specific = {'data': {}}
        throttle = throttling.Throttle(prefix=['cgcmd'])

        with mock.patch('cinder.volume.volume_utils.check_for_odirect_support',
                        return_value=True):
            output = image_utils.convert_image(source, dest, out_format,
                                               throttle=throttle)

            my_call = mock.call(source, run_as_root=True)
            mock_info.assert_has_calls([my_call, my_call])
            self.assertIsNone(output)
            mock_exec.assert_called_once_with('cgcmd', 'qemu-img', 'convert',
                                              '-O', out_format, '-t', 'none',
                                              source, dest, run_as_root=True)

        mock_exec.reset_mock()

        with mock.patch('cinder.volume.volume_utils.check_for_odirect_support',
                        return_value=False):
            output = image_utils.convert_image(source, dest, out_format)

            self.assertIsNone(output)
            mock_exec.assert_called_once_with('qemu-img', 'convert',
                                              '-O', out_format, source, dest,
                                              run_as_root=True)

    @mock.patch('cinder.volume.volume_utils.check_for_odirect_support',
                return_value=True)
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.utils.execute')
    @mock.patch('cinder.utils.is_blk_device', return_value=False)
    def test_defaults_not_block_dev_with_size_info(self, mock_isblk,
                                                   mock_exec,
                                                   mock_info,
                                                   mock_odirect):
        source = mock.sentinel.source
        dest = mock.sentinel.dest
        out_format = mock.sentinel.out_format
        out_subformat = 'fake_subformat'
        mock_info.return_value.virtual_size = 1048576

        output = image_utils.convert_image(source, dest, out_format,
                                           out_subformat=out_subformat)

        self.assertIsNone(output)
        mock_exec.assert_called_once_with('qemu-img', 'convert', '-O',
                                          out_format, '-o',
                                          'subformat=%s' % out_subformat,
                                          source, dest,
                                          run_as_root=True)

    @mock.patch('cinder.volume.volume_utils.check_for_odirect_support',
                return_value=True)
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.utils.execute')
    @mock.patch('cinder.utils.is_blk_device', return_value=False)
    def test_defaults_not_block_dev_without_size_info(self,
                                                      mock_isblk,
                                                      mock_exec,
                                                      mock_info,
                                                      mock_odirect):
        source = mock.sentinel.source
        dest = mock.sentinel.dest
        out_format = mock.sentinel.out_format
        out_subformat = 'fake_subformat'

        output = image_utils.convert_image(source, dest, out_format,
                                           out_subformat=out_subformat)

        self.assertIsNone(output)
        mock_exec.assert_called_once_with('qemu-img', 'convert', '-O',
                                          out_format, '-o',
                                          'subformat=%s' % out_subformat,
                                          source, dest,
                                          run_as_root=True)

    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.utils.execute')
    @mock.patch('cinder.utils.is_blk_device', return_value=True)
    def test_defaults_block_dev_ami_img(self, mock_isblk, mock_exec,
                                        mock_info):
        source = mock.sentinel.source
        dest = mock.sentinel.dest
        out_format = mock.sentinel.out_format
        mock_info.return_value.virtual_size = 1048576

        with mock.patch('cinder.volume.volume_utils.check_for_odirect_support',
                        return_value=True):
            output = image_utils.convert_image(source, dest, out_format,
                                               src_format='AMI')

            self.assertIsNone(output)
            mock_exec.assert_called_once_with('qemu-img', 'convert',
                                              '-O', out_format, '-t', 'none',
                                              source, dest, run_as_root=True)

    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.utils.execute')
    @mock.patch('cinder.utils.is_blk_device', return_value=False)
    @mock.patch('cinder.volume.volume_utils.check_for_odirect_support')
    def test_convert_to_vhd(self, mock_check_odirect, mock_isblk,
                            mock_exec, mock_info):
        source = mock.sentinel.source
        dest = mock.sentinel.dest
        out_format = "vhd"
        mock_info.return_value.virtual_size = 1048576

        output = image_utils.convert_image(source, dest, out_format)
        self.assertIsNone(output)
        # Qemu uses the legacy "vpc" format name, instead of "vhd".
        mock_exec.assert_called_once_with('qemu-img', 'convert',
                                          '-O', 'vpc',
                                          source, dest, run_as_root=True)

    @ddt.data(True, False)
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.utils.execute')
    @mock.patch('cinder.utils.is_blk_device', return_value=False)
    def test_convert_to_qcow2(self,
                              compress_option,
                              mock_isblk, mock_exec, mock_info):
        self.override_config('image_compress_on_upload', compress_option)
        source = mock.sentinel.source
        dest = mock.sentinel.dest
        out_format = 'qcow2'
        mock_info.return_value.virtual_size = 1048576

        image_utils.convert_image(source,
                                  dest,
                                  out_format,
                                  compress=True)

        exec_args = ['qemu-img', 'convert', '-O', 'qcow2']
        if compress_option:
            exec_args.append('-c')
        exec_args.extend((source, dest))
        mock_exec.assert_called_once_with(*exec_args,
                                          run_as_root=True)

    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.utils.execute')
    @mock.patch('cinder.utils.is_blk_device', return_value=False)
    def test_convert_disable_sparse(self, mock_isblk,
                                    mock_exec, mock_info):
        source = mock.sentinel.source
        dest = mock.sentinel.dest
        out_format = mock.sentinel.out_format
        mock_info.return_value.virtual_size = 1048576

        output = image_utils.convert_image(source, dest, out_format,
                                           disable_sparse=True)

        self.assertIsNone(output)
        mock_exec.assert_called_once_with('qemu-img', 'convert',
                                          '-O', out_format, '-S', '0', source,
                                          dest, run_as_root=True)

    @mock.patch('cinder.volume.volume_utils.check_for_odirect_support',
                return_value=True)
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.utils.execute')
    @mock.patch('cinder.utils.is_blk_device', return_value=False)
    @mock.patch('os.path.dirname', return_value='fakedir')
    @mock.patch('os.path.ismount', return_value=True)
    @mock.patch('oslo_utils.fileutils.ensure_tree')
    @mock.patch('cinder.image.image_utils.utils.tempdir')
    @mock.patch.object(image_utils.LOG, 'error')
    def test_not_enough_conversion_space(self,
                                         mock_log,
                                         mock_tempdir,
                                         mock_make,
                                         mock_ismount,
                                         mock_dirname,
                                         mock_isblk,
                                         mock_exec,
                                         mock_info,
                                         mock_odirect):
        source = mock.sentinel.source
        self.flags(image_conversion_dir='fakedir')
        dest = ['fakedir']
        out_format = mock.sentinel.out_format
        mock_exec.side_effect = processutils.ProcessExecutionError(
            stderr='No space left on device')
        self.assertRaises(processutils.ProcessExecutionError,
                          image_utils.convert_image,
                          source, dest, out_format)
        mock_log.assert_called_with('Insufficient free space on fakedir for'
                                    ' image conversion.')

    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.utils.execute')
    @mock.patch('cinder.image.image_utils._get_qemu_convert_cmd')
    @mock.patch('cinder.utils.is_blk_device', return_value=False)
    @mock.patch.object(image_utils.LOG, 'info')
    @mock.patch.object(image_utils.LOG, 'debug')
    def test__convert_image_no_virt_size(self,
                                         mock_debug_log,
                                         mock_info_log,
                                         mock_isblk,
                                         mock_cmd,
                                         mock_execute,
                                         mock_info):
        """Make sure we don't try to do math with a None value"""
        prefix = ('cgexec', '-g', 'blkio:cg')
        source = '/source'
        dest = '/dest'
        out_format = 'unspecified'

        # 1. no qemu_img_info passed in and qemu_img_info() raises exc
        mock_info.side_effect = processutils.ProcessExecutionError
        image_utils._convert_image(prefix, source, dest, out_format)
        mock_debug_log.assert_not_called()
        log_msg = mock_info_log.call_args.args[0]
        self.assertIn("image size is unavailable", log_msg)

        mock_info.reset_mock(side_effect=True)
        mock_info_log.reset_mock()

        # 2. no qemu_img_info passed in, returned obj has no virtual_size
        mock_info.return_value = imageutils.QemuImgInfo()
        image_utils._convert_image(prefix, source, dest, out_format)
        mock_debug_log.assert_not_called()
        log_msg = mock_info_log.call_args.args[0]
        self.assertIn("image size is unavailable", log_msg)

        mock_info.reset_mock(return_value=True)
        mock_info_log.reset_mock()

        # 3. no qemu_img_info passed in, returned obj has virtual_size
        mock_info.return_value = imageutils.QemuImgInfo(
            '{"virtual-size": 1073741824}', format='json')
        image_utils._convert_image(prefix, source, dest, out_format)
        log_msg = mock_debug_log.call_args.args[0]
        self.assertIn("Image conversion details", log_msg)
        log_msg = mock_info_log.call_args.args[0]
        self.assertIn("Converted", log_msg)

        mock_info.reset_mock()
        mock_debug_log.reset_mock()
        mock_info_log.reset_mock()

        # 4. qemu_img_info passed in but without virtual_size
        src_img_info = imageutils.QemuImgInfo()
        image_utils._convert_image(prefix, source, dest, out_format,
                                   src_img_info=src_img_info)
        mock_info.assert_not_called()
        mock_debug_log.assert_not_called()
        log_msg = mock_info_log.call_args.args[0]
        self.assertIn("image size is unavailable", log_msg)

        mock_info_log.reset_mock()

        # 5. qemu_img_info passed in with virtual_size
        src_img_info = imageutils.QemuImgInfo('{"virtual-size": 1073741824}',
                                              format='json')
        image_utils._convert_image(prefix, source, dest, out_format,
                                   src_img_info=src_img_info)
        mock_info.assert_not_called()
        log_msg = mock_debug_log.call_args.args[0]
        self.assertIn("Image conversion details", log_msg)
        log_msg = mock_info_log.call_args.args[0]
        self.assertIn("Converted", log_msg)


@ddt.ddt
class TestResizeImage(test.TestCase):
    @mock.patch('cinder.utils.execute')
    @ddt.data(None, 'raw', 'qcow2')
    def test_defaults(self, file_format, mock_exec):
        source = mock.sentinel.source
        size = mock.sentinel.size
        output = image_utils.resize_image(source, size,
                                          file_format=file_format)
        self.assertIsNone(output)
        if file_format:
            mock_exec.assert_called_once_with(
                'qemu-img', 'resize', '-f', file_format, source,
                'sentinel.sizeG', run_as_root=False)
        else:
            mock_exec.assert_called_once_with('qemu-img', 'resize',
                                              source, 'sentinel.sizeG',
                                              run_as_root=False)

    @mock.patch('cinder.utils.execute')
    @ddt.data(None, 'raw', 'qcow2')
    def test_run_as_root(self, file_format, mock_exec):
        source = mock.sentinel.source
        size = mock.sentinel.size
        output = image_utils.resize_image(source, size, run_as_root=True,
                                          file_format=file_format)
        self.assertIsNone(output)
        if file_format:
            mock_exec.assert_called_once_with(
                'qemu-img', 'resize', '-f', file_format, source,
                'sentinel.sizeG', run_as_root=True)
        else:
            mock_exec.assert_called_once_with('qemu-img', 'resize',
                                              source, 'sentinel.sizeG',
                                              run_as_root=True)


class TestFetch(test.TestCase):
    @mock.patch('eventlet.tpool.Proxy')
    @mock.patch('os.stat')
    @mock.patch('cinder.image.image_utils.fileutils')
    def test_defaults(self, mock_fileutils, mock_stat, mock_proxy):
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
        mock_proxy.assert_called_once_with(mock_open.return_value)
        image_service.download.assert_called_once_with(ctxt, image_id,
                                                       mock_proxy.return_value)
        mock_open.assert_called_once_with(path, 'wb')
        mock_fileutils.remove_path_on_error.assert_called_once_with(path)
        (mock_fileutils.remove_path_on_error.return_value.__enter__
            .assert_called_once_with())
        (mock_fileutils.remove_path_on_error.return_value.__exit__
            .assert_called_once_with(None, None, None))

    def test_fetch_enospc(self):
        context = mock.sentinel.context
        image_service = mock.Mock()
        image_id = mock.sentinel.image_id
        e = exception.ImageTooBig(image_id=image_id, reason = "fake")
        e.errno = errno.ENOSPC
        image_service.download.side_effect = e
        path = '/test_path'
        _user_id = mock.sentinel._user_id
        _project_id = mock.sentinel._project_id

        with mock.patch('cinder.image.image_utils.open',
                        new=mock.mock_open(), create=True):
            self.assertRaises(exception.ImageTooBig,
                              image_utils.fetch,
                              context, image_service, image_id, path,
                              _user_id, _project_id)

    def test_fetch_ioerror(self):
        context = mock.sentinel.context
        image_service = mock.Mock()
        image_id = mock.sentinel.image_id
        e = IOError()
        e.errno = errno.ECONNRESET
        e.strerror = 'Some descriptive message'
        image_service.download.side_effect = e
        path = '/test_path'
        _user_id = mock.sentinel._user_id
        _project_id = mock.sentinel._project_id

        with mock.patch('cinder.image.image_utils.open',
                        new=mock.mock_open(), create=True):
            self.assertRaisesRegex(exception.ImageDownloadFailed,
                                   e.strerror,
                                   image_utils.fetch,
                                   context, image_service, image_id, path,
                                   _user_id, _project_id)


class MockVerifier(object):
    def update(self, data):
        return

    def verify(self):
        return True


class BadVerifier(object):
    def update(self, data):
        return

    def verify(self):
        raise cryptography.exceptions.InvalidSignature(
            'Invalid signature.'
        )


class TestVerifyImageSignature(test.TestCase):

    @mock.patch('cinder.image.image_utils.open', new_callable=mock.mock_open)
    @mock.patch('cursive.signature_utils.get_verifier')
    @mock.patch('oslo_utils.fileutils.remove_path_on_error')
    def test_image_signature_verify_failed(self,
                                           mock_remove, mock_get, mock_open):
        ctxt = mock.sentinel.context
        metadata = {'name': 'test image',
                    'is_public': False,
                    'protected': False,
                    'properties':
                        {'img_signature_certificate_uuid': 'fake_uuid',
                         'img_signature_hash_method': 'SHA-256',
                         'img_signature': 'signature',
                         'img_signature_key_type': 'RSA-PSS'}}

        class FakeImageService(object):
            def show(self, context, image_id):
                return metadata

        self.flags(verify_glance_signatures='enabled')
        mock_get.return_value = BadVerifier()

        self.assertRaises(exception.ImageSignatureVerificationException,
                          image_utils.verify_glance_image_signature,
                          ctxt, FakeImageService(), 'fake_id',
                          'fake_path')
        mock_get.assert_called_once_with(
            context=ctxt,
            img_signature_certificate_uuid='fake_uuid',
            img_signature_hash_method='SHA-256',
            img_signature='signature',
            img_signature_key_type='RSA-PSS')

    @mock.patch('cursive.signature_utils.get_verifier')
    def test_image_signature_metadata_missing(self, mock_get):
        ctxt = mock.sentinel.context
        metadata = {'name': 'test image',
                    'is_public': False,
                    'protected': False,
                    'properties': {}}

        class FakeImageService(object):
            def show(self, context, image_id):
                return metadata

        self.flags(verify_glance_signatures='enabled')

        result = image_utils.verify_glance_image_signature(
            ctxt, FakeImageService(), 'fake_id', 'fake_path')
        self.assertFalse(result)
        mock_get.assert_not_called()

    @mock.patch('cursive.signature_utils.get_verifier')
    def test_image_signature_metadata_incomplete(self, mock_get):
        ctxt = mock.sentinel.context
        metadata = {'name': 'test image',
                    'is_public': False,
                    'protected': False,
                    'properties':
                        {'img_signature_certificate_uuid': None,
                         'img_signature_hash_method': 'SHA-256',
                         'img_signature': 'signature',
                         'img_signature_key_type': 'RSA-PSS'}}

        class FakeImageService(object):
            def show(self, context, image_id):
                return metadata

        self.flags(verify_glance_signatures='enabled')

        self.assertRaises(exception.InvalidSignatureImage,
                          image_utils.verify_glance_image_signature, ctxt,
                          FakeImageService(), 'fake_id', 'fake_path')
        mock_get.assert_not_called()

    @mock.patch('cinder.image.image_utils.open', new_callable=mock.mock_open)
    @mock.patch('eventlet.tpool.execute')
    @mock.patch('cursive.signature_utils.get_verifier')
    @mock.patch('oslo_utils.fileutils.remove_path_on_error')
    def test_image_signature_verify_success(self, mock_remove, mock_get,
                                            mock_exec, mock_open):
        ctxt = mock.sentinel.context
        metadata = {'name': 'test image',
                    'is_public': False,
                    'protected': False,
                    'properties':
                        {'img_signature_certificate_uuid': 'fake_uuid',
                         'img_signature_hash_method': 'SHA-256',
                         'img_signature': 'signature',
                         'img_signature_key_type': 'RSA-PSS'}}

        class FakeImageService(object):
            def show(self, context, image_id):
                return metadata

        self.flags(verify_glance_signatures='enabled')
        mock_get.return_value = MockVerifier()

        result = image_utils.verify_glance_image_signature(
            ctxt, FakeImageService(), 'fake_id', 'fake_path')
        self.assertTrue(result)
        mock_exec.assert_called_once_with(
            image_utils._verify_image,
            mock_open.return_value.__enter__.return_value,
            mock_get.return_value)

        mock_get.assert_called_once_with(
            context=ctxt,
            img_signature_certificate_uuid='fake_uuid',
            img_signature_hash_method='SHA-256',
            img_signature='signature',
            img_signature_key_type='RSA-PSS')


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
        mock_info.assert_called_once_with(dest,
                                          run_as_root=True,
                                          force_share=False)
        mock_fileutils.remove_path_on_error.assert_called_once_with(dest)
        (mock_fileutils.remove_path_on_error.return_value.__enter__
            .assert_called_once_with())
        (mock_fileutils.remove_path_on_error.return_value.__exit__
            .assert_called_once_with(None, None, None))

    @mock.patch('cinder.image.image_utils.check_virtual_size')
    @mock.patch('cinder.image.image_utils.check_available_space')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.fileutils')
    @mock.patch('cinder.image.image_utils.fetch')
    def test_kwargs(self, mock_fetch, mock_fileutils, mock_info,
                    mock_check_space, mock_check_size):
        ctxt = mock.sentinel.context
        image_service = FakeImageService()
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        mock_data = mock_info.return_value
        mock_data.file_format = 'test_format'
        mock_data.backing_file = None
        mock_data.virtual_size = 1

        output = image_utils.fetch_verify_image(
            ctxt, image_service, image_id, dest)
        self.assertIsNone(output)
        mock_fetch.assert_called_once_with(ctxt, image_service, image_id,
                                           dest, None, None)
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


class TestTemporaryDir(test.TestCase):
    @mock.patch('oslo_utils.fileutils.ensure_tree')
    @mock.patch('cinder.image.image_utils.utils.tempdir')
    def test_conv_dir_exists(self, mock_tempdir, mock_make):
        self.flags(image_conversion_dir='fake_conv_dir')

        output = image_utils.temporary_dir()

        self.assertTrue(mock_make.called)
        mock_tempdir.assert_called_once_with(dir='fake_conv_dir')
        self.assertEqual(output, mock_tempdir.return_value)

    @mock.patch('oslo_utils.fileutils.ensure_tree')
    @mock.patch('cinder.image.image_utils.utils.tempdir')
    def test_create_conv_dir(self, mock_tempdir, mock_make):
        self.flags(image_conversion_dir='fake_conv_dir')

        output = image_utils.temporary_dir()

        mock_make.assert_called_once_with('fake_conv_dir')
        mock_tempdir.assert_called_once_with(dir='fake_conv_dir')
        self.assertEqual(output, mock_tempdir.return_value)

    @mock.patch('oslo_utils.fileutils.ensure_tree')
    @mock.patch('cinder.image.image_utils.utils.tempdir')
    def test_no_conv_dir(self, mock_tempdir, mock_make):
        self.flags(image_conversion_dir=None)

        output = image_utils.temporary_dir()

        self.assertTrue(mock_make.called)
        mock_tempdir.assert_called_once_with(dir=None)
        self.assertEqual(output, mock_tempdir.return_value)


@ddt.ddt
class TestUploadVolume(test.TestCase):
    @ddt.data((mock.sentinel.disk_format, mock.sentinel.disk_format, True),
              (mock.sentinel.disk_format, mock.sentinel.disk_format, False),
              ('ploop', 'parallels', True),
              ('ploop', 'parallels', False))
    @mock.patch('eventlet.tpool.Proxy')
    @mock.patch('cinder.image.image_utils.open', new_callable=mock.mock_open)
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.os')
    def test_diff_format(self, image_format, mock_os, mock_temp, mock_convert,
                         mock_info, mock_open, mock_proxy):
        input_format, output_format, do_compress = image_format
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_meta = {'id': 'test_id',
                      'disk_format': input_format,
                      'container_format': mock.sentinel.container_format}
        volume_path = mock.sentinel.volume_path
        mock_os.name = 'posix'
        data = mock_info.return_value
        data.file_format = output_format
        data.backing_file = None
        temp_file = mock_temp.return_value.__enter__.return_value

        output = image_utils.upload_volume(ctxt, image_service, image_meta,
                                           volume_path, compress=do_compress)

        self.assertIsNone(output)
        mock_convert.assert_called_once_with(volume_path,
                                             temp_file,
                                             output_format,
                                             run_as_root=True,
                                             compress=do_compress,
                                             image_id=image_meta['id'],
                                             data=data)
        mock_info.assert_called_with(temp_file, run_as_root=True)
        self.assertEqual(2, mock_info.call_count)
        mock_open.assert_called_once_with(temp_file, 'rb')
        mock_proxy.assert_called_once_with(
            mock_open.return_value.__enter__.return_value)
        image_service.update.assert_called_once_with(
            ctxt, image_meta['id'], {}, mock_proxy.return_value,
            store_id=None, base_image_ref=None)

    @mock.patch('eventlet.tpool.Proxy')
    @mock.patch('cinder.image.image_utils.utils.temporary_chown')
    @mock.patch('cinder.image.image_utils.open', new_callable=mock.mock_open)
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.os')
    def test_same_format(self, mock_os, mock_temp, mock_convert, mock_info,
                         mock_open, mock_chown, mock_proxy):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_meta = {'id': 'test_id',
                      'disk_format': 'raw',
                      'container_format': mock.sentinel.container_format}
        volume_path = mock.sentinel.volume_path
        mock_os.name = 'posix'
        mock_os.access.return_value = False

        output = image_utils.upload_volume(ctxt, image_service, image_meta,
                                           volume_path)

        self.assertIsNone(output)
        self.assertFalse(mock_convert.called)
        self.assertFalse(mock_info.called)
        mock_chown.assert_called_once_with(volume_path)
        mock_open.assert_called_once_with(volume_path, 'rb')
        mock_proxy.assert_called_once_with(
            mock_open.return_value.__enter__.return_value)
        image_service.update.assert_called_once_with(
            ctxt, image_meta['id'], {}, mock_proxy.return_value,
            store_id=None, base_image_ref=None)

    @mock.patch('cinder.image.accelerator.ImageAccel._get_engine')
    @mock.patch('cinder.image.accelerator.ImageAccel.is_engine_ready',
                return_value = True)
    @mock.patch('eventlet.tpool.Proxy')
    @mock.patch('cinder.image.image_utils.utils.temporary_chown')
    @mock.patch('cinder.image.image_utils.open', new_callable=mock.mock_open)
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.os')
    def test_same_format_compressed(self, mock_os, mock_temp, mock_convert,
                                    mock_info, mock_open,
                                    mock_chown, mock_proxy,
                                    mock_engine_ready, mock_get_engine):
        class fakeEngine(object):

            def __init__(self):
                pass

            def compress_img(self, src, dest, run_as_root):
                pass

        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_meta = {'id': 'test_id',
                      'disk_format': 'raw',
                      'container_format': 'compressed'}
        self.flags(allow_compression_on_image_upload=True)
        volume_path = mock.sentinel.volume_path
        mock_os.name = 'posix'
        data = mock_info.return_value
        data.file_format = 'raw'
        data.backing_file = None
        temp_file = mock_temp.return_value.__enter__.return_value
        mock_engine = mock.Mock(spec=fakeEngine)
        mock_get_engine.return_value = mock_engine

        output = image_utils.upload_volume(ctxt, image_service, image_meta,
                                           volume_path)

        self.assertIsNone(output)
        mock_convert.assert_called_once_with(volume_path,
                                             temp_file,
                                             'raw',
                                             compress=True,
                                             run_as_root=True,
                                             image_id=image_meta['id'],
                                             data=data)
        mock_info.assert_called_with(temp_file, run_as_root=True)
        self.assertEqual(2, mock_info.call_count)
        mock_open.assert_called_once_with(temp_file, 'rb')
        mock_proxy.assert_called_once_with(
            mock_open.return_value.__enter__.return_value)
        image_service.update.assert_called_once_with(
            ctxt, image_meta['id'], {}, mock_proxy.return_value,
            store_id=None, base_image_ref=None)
        mock_engine.compress_img.assert_called()

    @mock.patch('eventlet.tpool.Proxy')
    @mock.patch('cinder.image.image_utils.utils.temporary_chown')
    @mock.patch('cinder.image.image_utils.open', new_callable=mock.mock_open)
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.os')
    def test_same_format_on_nt(self, mock_os, mock_temp, mock_convert,
                               mock_info, mock_open, mock_chown,
                               mock_proxy):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_meta = {'id': 'test_id',
                      'disk_format': 'raw',
                      'container_format': 'bare'}
        volume_path = mock.sentinel.volume_path
        mock_os.name = 'nt'
        mock_os.access.return_value = False

        output = image_utils.upload_volume(ctxt, image_service, image_meta,
                                           volume_path)

        self.assertIsNone(output)
        self.assertFalse(mock_convert.called)
        self.assertFalse(mock_info.called)
        mock_open.assert_called_once_with(volume_path, 'rb')
        mock_proxy.assert_called_once_with(
            mock_open.return_value.__enter__.return_value)
        image_service.update.assert_called_once_with(
            ctxt, image_meta['id'], {}, mock_proxy.return_value,
            store_id=None, base_image_ref=None)

    @mock.patch('cinder.image.accelerator.ImageAccel._get_engine')
    @mock.patch('cinder.image.accelerator.ImageAccel.is_engine_ready',
                return_value = True)
    @mock.patch('eventlet.tpool.Proxy')
    @mock.patch('cinder.image.image_utils.utils.temporary_chown')
    @mock.patch('cinder.image.image_utils.open', new_callable=mock.mock_open)
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.os')
    def test_same_format_on_nt_compressed(self, mock_os, mock_temp,
                                          mock_convert, mock_info,
                                          mock_open,
                                          mock_chown, mock_proxy,
                                          mock_engine_ready, mock_get_engine):
        class fakeEngine(object):

            def __init__(self):
                pass

            def compress_img(self, src, dest, run_as_root):
                pass

        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_meta = {'id': 'test_id',
                      'disk_format': 'raw',
                      'container_format': 'compressed'}
        self.flags(allow_compression_on_image_upload=True)
        volume_path = mock.sentinel.volume_path
        mock_os.name = 'posix'
        data = mock_info.return_value
        data.file_format = 'raw'
        data.backing_file = None
        temp_file = mock_temp.return_value.__enter__.return_value
        mock_engine = mock.Mock(spec=fakeEngine)
        mock_get_engine.return_value = mock_engine

        output = image_utils.upload_volume(ctxt, image_service, image_meta,
                                           volume_path)

        self.assertIsNone(output)
        mock_convert.assert_called_once_with(volume_path,
                                             temp_file,
                                             'raw',
                                             compress=True,
                                             run_as_root=True,
                                             image_id=image_meta['id'],
                                             data=data)
        mock_info.assert_called_with(temp_file, run_as_root=True)
        self.assertEqual(2, mock_info.call_count)
        mock_open.assert_called_once_with(temp_file, 'rb')
        mock_proxy.assert_called_once_with(
            mock_open.return_value.__enter__.return_value)
        image_service.update.assert_called_once_with(
            ctxt, image_meta['id'], {}, mock_proxy.return_value,
            store_id=None, base_image_ref=None)
        mock_engine.compress_img.assert_called()

    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.os')
    def test_convert_error(self, mock_os, mock_temp, mock_convert, mock_info):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_meta = {'id': 'test_id',
                      'disk_format': mock.sentinel.disk_format,
                      'container_format': mock.sentinel.container_format}
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
                                             run_as_root=True,
                                             compress=True,
                                             image_id=image_meta['id'],
                                             data=data)
        mock_info.assert_called_with(temp_file, run_as_root=True)
        self.assertEqual(2, mock_info.call_count)
        self.assertFalse(image_service.update.called)

    @mock.patch('eventlet.tpool.Proxy')
    @mock.patch('cinder.image.image_utils.utils.temporary_chown')
    @mock.patch('cinder.image.image_utils.open', new_callable=mock.mock_open)
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.os')
    def test_base_image_ref(self, mock_os, mock_temp, mock_convert, mock_info,
                            mock_open, mock_chown, mock_proxy):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_meta = {'id': 'test_id',
                      'disk_format': 'raw',
                      'container_format': mock.sentinel.container_format}
        volume_path = mock.sentinel.volume_path
        mock_os.name = 'posix'
        mock_os.access.return_value = False

        image_utils.upload_volume(ctxt, image_service, image_meta,
                                  volume_path, base_image_ref='xyz')

        mock_open.assert_called_once_with(volume_path, 'rb')
        image_service.update.assert_called_once_with(
            ctxt, image_meta['id'], {}, mock_proxy.return_value,
            store_id=None, base_image_ref='xyz')


class TestFetchToVhd(test.TestCase):
    @mock.patch('cinder.image.image_utils.fetch_to_volume_format')
    def test_defaults(self, mock_fetch_to):
        ctxt = mock.sentinel.context
        image_service = mock.sentinel.image_service
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        blocksize = mock.sentinel.blocksize
        out_subformat = 'fake_subformat'

        output = image_utils.fetch_to_vhd(ctxt, image_service, image_id,
                                          dest, blocksize,
                                          volume_subformat=out_subformat)
        self.assertIsNone(output)
        mock_fetch_to.assert_called_once_with(ctxt, image_service, image_id,
                                              dest, 'vpc', blocksize,
                                              volume_subformat=out_subformat,
                                              user_id=None,
                                              project_id=None,
                                              run_as_root=True,
                                              disable_sparse=False)

    @mock.patch('cinder.image.image_utils.check_available_space')
    @mock.patch('cinder.image.image_utils.fetch_to_volume_format')
    def test_kwargs(self, mock_fetch_to, mock_check_space):
        ctxt = mock.sentinel.context
        image_service = mock.sentinel.image_service
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        blocksize = mock.sentinel.blocksize
        user_id = mock.sentinel.user_id
        project_id = mock.sentinel.project_id
        run_as_root = mock.sentinel.run_as_root
        out_subformat = 'fake_subformat'

        output = image_utils.fetch_to_vhd(ctxt, image_service, image_id,
                                          dest, blocksize, user_id=user_id,
                                          project_id=project_id,
                                          run_as_root=run_as_root,
                                          volume_subformat=out_subformat)
        self.assertIsNone(output)
        mock_fetch_to.assert_called_once_with(ctxt, image_service, image_id,
                                              dest, 'vpc', blocksize,
                                              volume_subformat=out_subformat,
                                              user_id=user_id,
                                              project_id=project_id,
                                              run_as_root=run_as_root,
                                              disable_sparse=False)


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
                                              dest, 'raw', blocksize,
                                              user_id=None, project_id=None,
                                              size=None, run_as_root=True,
                                              disable_sparse=False)

    @mock.patch('cinder.image.image_utils.check_available_space')
    @mock.patch('cinder.image.image_utils.fetch_to_volume_format')
    def test_kwargs(self, mock_fetch_to, mock_check_space):
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
                                              dest, 'raw', blocksize,
                                              user_id=user_id, size=size,
                                              project_id=project_id,
                                              run_as_root=run_as_root,
                                              disable_sparse=False)


class FakeImageService(object):
    def __init__(self, image_service=None, disk_format='raw'):
        self.temp_images = None
        self.disk_format = disk_format

    def show(self, context, image_id):
        return {'size': 2 * units.Gi,
                'disk_format': self.disk_format,
                'container_format': 'bare',
                'status': 'active'}


@ddt.ddt(testNameFormat=ddt.TestNameFormat.INDEX_ONLY)
class TestFetchToVolumeFormat(test.TestCase):
    @mock.patch('cinder.image.image_utils.check_available_space')
    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.volume_utils.copy_volume')
    @mock.patch(
        'cinder.image.image_utils.replace_xenserver_image_with_coalesced_vhd')
    @mock.patch('cinder.image.image_utils.is_xenserver_format',
                return_value=False)
    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.temporary_file')
    def test_defaults(self, mock_temp, mock_info, mock_fetch,
                      mock_is_xen, mock_repl_xen, mock_copy, mock_convert,
                      mock_check_space):
        ctxt = mock.sentinel.context
        ctxt.user_id = mock.sentinel.user_id
        image_service = FakeImageService()
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        volume_format = mock.sentinel.volume_format
        out_subformat = None
        blocksize = mock.sentinel.blocksize

        disk_format = 'raw'

        data = mock_info.return_value
        data.file_format = disk_format
        data.backing_file = None
        data.virtual_size = 1234
        tmp = mock_temp.return_value.__enter__.return_value

        output = image_utils.fetch_to_volume_format(ctxt, image_service,
                                                    image_id, dest,
                                                    volume_format, blocksize)

        self.assertIsNone(output)
        mock_temp.assert_called_once_with(prefix='image_download_%s_' %
                                          image_id)
        mock_info.assert_has_calls([
            mock.call(tmp, force_share=False, run_as_root=True),
            mock.call(tmp, run_as_root=True)])
        mock_fetch.assert_called_once_with(ctxt, image_service, image_id,
                                           tmp, None, None)
        self.assertFalse(mock_repl_xen.called)
        self.assertFalse(mock_copy.called)
        mock_convert.assert_called_once_with(tmp, dest, volume_format,
                                             out_subformat=out_subformat,
                                             run_as_root=True,
                                             src_format=disk_format,
                                             image_id=image_id,
                                             data=data,
                                             disable_sparse=False)

    @mock.patch('cinder.image.image_utils.check_virtual_size')
    @mock.patch('cinder.image.image_utils.check_available_space')
    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.volume_utils.copy_volume')
    @mock.patch(
        'cinder.image.image_utils.replace_xenserver_image_with_coalesced_vhd')
    @mock.patch('cinder.image.image_utils.is_xenserver_format',
                return_value=False)
    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.temporary_file')
    def test_kwargs(self, mock_temp, mock_info, mock_fetch,
                    mock_is_xen, mock_repl_xen, mock_copy, mock_convert,
                    mock_check_space, mock_check_size):
        ctxt = mock.sentinel.context
        disk_format = 'ploop'
        qemu_img_format = image_utils.QEMU_IMG_FORMAT_MAP[disk_format]
        image_service = FakeImageService(disk_format=disk_format)
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        volume_format = mock.sentinel.volume_format
        out_subformat = None
        blocksize = mock.sentinel.blocksize
        ctxt.user_id = user_id = mock.sentinel.user_id
        project_id = mock.sentinel.project_id
        size = 4321
        run_as_root = mock.sentinel.run_as_root

        data = mock_info.return_value
        data.file_format = qemu_img_format
        data.backing_file = None
        data.virtual_size = 1234
        tmp = mock_temp.return_value.__enter__.return_value

        output = image_utils.fetch_to_volume_format(
            ctxt, image_service, image_id, dest, volume_format, blocksize,
            user_id=user_id, project_id=project_id, size=size,
            run_as_root=run_as_root)

        self.assertIsNone(output)
        mock_temp.assert_called_once_with(prefix='image_download_%s_' %
                                          image_id)
        mock_info.assert_has_calls([
            mock.call(tmp, force_share=False, run_as_root=run_as_root),
            mock.call(tmp, run_as_root=run_as_root)])
        mock_fetch.assert_called_once_with(ctxt, image_service, image_id,
                                           tmp, user_id, project_id)
        self.assertFalse(mock_repl_xen.called)
        self.assertFalse(mock_copy.called)
        mock_convert.assert_called_once_with(tmp, dest, volume_format,
                                             out_subformat=out_subformat,
                                             run_as_root=run_as_root,
                                             src_format=qemu_img_format,
                                             image_id=image_id,
                                             data=data,
                                             disable_sparse=False)
        mock_check_size.assert_called_once_with(data.virtual_size,
                                                size, image_id)

    @ddt.data(('raw', 'qcow2', False),
              ('raw', 'raw', False),
              ('raw', 'raw', True))
    def test_check_image_conversion(self, conversion_opts):
        image_disk_format, volume_format, image_conversion_disable = \
            conversion_opts
        self.flags(image_conversion_disable=image_conversion_disable)
        self.assertIsNone(image_utils.check_image_conversion_disable(
            image_disk_format, volume_format, fake.IMAGE_ID))

    @ddt.data((True, 'volume can only be uploaded in the format'),
              (False, 'must use an image with the disk_format property'))
    def test_check_image_conversion_disable(self, info):
        # NOTE: the error message is different depending on direction,
        # where True means upload
        direction, message_fragment = info
        self.flags(image_conversion_disable=True)
        exc = self.assertRaises(exception.ImageConversionNotAllowed,
                                image_utils.check_image_conversion_disable,
                                'foo', 'bar', fake.IMAGE_ID,
                                upload=direction)
        if direction:
            self.assertIn(message_fragment, str(exc))
        else:
            self.assertIn(message_fragment, str(exc))

    @mock.patch('cinder.image.image_utils.check_virtual_size')
    @mock.patch('cinder.image.image_utils.check_available_space')
    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.volume_utils.copy_volume')
    @mock.patch(
        'cinder.image.image_utils.replace_xenserver_image_with_coalesced_vhd')
    @mock.patch('cinder.image.image_utils.is_xenserver_format',
                return_value=True)
    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.temporary_file')
    def test_convert_from_vhd(self, mock_temp, mock_info,
                              mock_fetch, mock_is_xen, mock_repl_xen,
                              mock_copy, mock_convert, mock_check_space,
                              mock_check_size):
        ctxt = mock.sentinel.context
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        volume_format = mock.sentinel.volume_format
        out_subformat = None
        blocksize = mock.sentinel.blocksize
        ctxt.user_id = user_id = mock.sentinel.user_id
        project_id = mock.sentinel.project_id
        size = 4321
        run_as_root = mock.sentinel.run_as_root

        disk_format = 'vhd'

        data = mock_info.return_value
        data.file_format = image_utils.QEMU_IMG_FORMAT_MAP[disk_format]
        data.backing_file = None
        data.virtual_size = 1234
        tmp = mock_temp.return_value.__enter__.return_value
        image_service = FakeImageService(disk_format=disk_format)
        expect_format = 'vpc'

        output = image_utils.fetch_to_volume_format(
            ctxt, image_service, image_id, dest, volume_format, blocksize,
            user_id=user_id, project_id=project_id, size=size,
            run_as_root=run_as_root)

        self.assertIsNone(output)
        mock_temp.assert_called_once_with(prefix='image_download_%s_' %
                                          image_id)
        mock_info.assert_has_calls([
            mock.call(tmp, force_share=False, run_as_root=run_as_root),
            mock.call(tmp, run_as_root=run_as_root)])
        mock_fetch.assert_called_once_with(ctxt, image_service, image_id,
                                           tmp, user_id, project_id)
        mock_repl_xen.assert_called_once_with(tmp)
        self.assertFalse(mock_copy.called)
        mock_convert.assert_called_once_with(tmp, dest, volume_format,
                                             out_subformat=out_subformat,
                                             run_as_root=run_as_root,
                                             src_format=expect_format,
                                             image_id=image_id,
                                             data=data,
                                             disable_sparse=False)

    @mock.patch('cinder.image.image_utils.check_virtual_size')
    @mock.patch('cinder.image.image_utils.check_available_space')
    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.volume_utils.copy_volume')
    @mock.patch('cinder.image.image_utils.is_xenserver_format',
                return_value=False)
    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.temporary_file')
    def test_convert_from_iso(self, mock_temp, mock_info,
                              mock_fetch, mock_is_xen, mock_copy,
                              mock_convert, mock_check_space,
                              mock_check_size):
        ctxt = mock.sentinel.context
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        volume_format = mock.sentinel.volume_format
        out_subformat = None
        blocksize = mock.sentinel.blocksize
        ctxt.user_id = user_id = mock.sentinel.user_id
        project_id = mock.sentinel.project_id
        size = 4321
        run_as_root = mock.sentinel.run_as_root

        disk_format = 'iso'

        data = mock_info.return_value
        data.file_format = image_utils.QEMU_IMG_FORMAT_MAP[disk_format]
        data.backing_file = None
        data.virtual_size = 1234
        tmp = mock_temp.return_value.__enter__.return_value
        image_service = FakeImageService(disk_format=disk_format)
        expect_format = 'raw'

        output = image_utils.fetch_to_volume_format(
            ctxt, image_service, image_id, dest, volume_format, blocksize,
            user_id=user_id, project_id=project_id, size=size,
            run_as_root=run_as_root)

        self.assertIsNone(output)
        mock_temp.assert_called_once_with(prefix='image_download_%s_' %
                                          image_id)
        mock_info.assert_has_calls([
            mock.call(tmp, force_share=False, run_as_root=run_as_root),
            mock.call(tmp, run_as_root=run_as_root)])
        mock_fetch.assert_called_once_with(ctxt, image_service, image_id,
                                           tmp, user_id, project_id)
        self.assertFalse(mock_copy.called)
        mock_convert.assert_called_once_with(tmp, dest, volume_format,
                                             out_subformat=out_subformat,
                                             run_as_root=run_as_root,
                                             src_format=expect_format,
                                             image_id=image_id,
                                             data=data,
                                             disable_sparse=False)

    @mock.patch('cinder.image.image_utils.check_available_space',
                new=mock.Mock())
    @mock.patch('cinder.image.image_utils.is_xenserver_format',
                new=mock.Mock(return_value=False))
    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.volume_utils.copy_volume')
    @mock.patch(
        'cinder.image.image_utils.replace_xenserver_image_with_coalesced_vhd')
    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.temporary_file')
    def test_temporary_images(self, mock_temp, mock_info,
                              mock_fetch, mock_repl_xen,
                              mock_copy, mock_convert):
        ctxt = mock.sentinel.context
        ctxt.user_id = mock.sentinel.user_id
        disk_format = 'ploop'
        qemu_img_format = image_utils.QEMU_IMG_FORMAT_MAP[disk_format]
        image_service = FakeImageService(disk_format=disk_format)
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        volume_format = mock.sentinel.volume_format
        out_subformat = None
        blocksize = mock.sentinel.blocksize

        data = mock_info.return_value
        data.file_format = qemu_img_format
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
                                                        blocksize,
                                                        disable_sparse=False)

        self.assertIsNone(output)
        self.assertEqual(2, mock_temp.call_count)
        mock_info.assert_has_calls([
            mock.call(tmp, force_share=False, run_as_root=True),
            mock.call(dummy, force_share=False, run_as_root=True),
            mock.call(tmp, run_as_root=True)])
        mock_fetch.assert_called_once_with(ctxt, image_service, image_id,
                                           tmp, None, None)
        self.assertFalse(mock_repl_xen.called)
        self.assertFalse(mock_copy.called)
        mock_convert.assert_called_once_with(tmp, dest, volume_format,
                                             out_subformat=out_subformat,
                                             run_as_root=True,
                                             src_format=qemu_img_format,
                                             image_id=image_id,
                                             data=data,
                                             disable_sparse=False)

    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.volume_utils.copy_volume')
    @mock.patch(
        'cinder.image.image_utils.replace_xenserver_image_with_coalesced_vhd')
    @mock.patch('cinder.image.image_utils.is_xenserver_format',
                return_value=False)
    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info',
                side_effect=processutils.ProcessExecutionError)
    @mock.patch('cinder.image.image_utils.temporary_file')
    def test_no_qemu_img_and_is_raw(self, mock_temp, mock_info,
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
        image_size_m = math.ceil(float(41126400) / units.Mi)

        output = image_utils.fetch_to_volume_format(
            ctxt, image_service, image_id, dest, volume_format, blocksize,
            user_id=user_id, project_id=project_id, size=size,
            run_as_root=run_as_root)

        self.assertIsNone(output)
        image_service.show.assert_called_once_with(ctxt, image_id)
        mock_temp.assert_called_once_with(prefix='image_download_%s_' %
                                          image_id)
        mock_info.assert_called_once_with(tmp,
                                          force_share=False,
                                          run_as_root=run_as_root)
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
    @mock.patch('cinder.image.image_utils.is_xenserver_format',
                return_value=False)
    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info',
                side_effect=processutils.ProcessExecutionError)
    @mock.patch('cinder.image.image_utils.temporary_file')
    def test_no_qemu_img_not_raw(self, mock_temp, mock_info,
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
        mock_temp.assert_called_once_with(prefix='image_download_%s_' %
                                          image_id)
        mock_info.assert_called_once_with(tmp,
                                          force_share=False,
                                          run_as_root=run_as_root)
        self.assertFalse(mock_fetch.called)
        self.assertFalse(mock_repl_xen.called)
        self.assertFalse(mock_copy.called)
        self.assertFalse(mock_convert.called)

    @mock.patch('cinder.image.image_utils.check_virtual_size')
    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.volume_utils.copy_volume')
    @mock.patch(
        'cinder.image.image_utils.replace_xenserver_image_with_coalesced_vhd')
    @mock.patch('cinder.image.image_utils.is_xenserver_format',
                return_value=False)
    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.temporary_file')
    def test_size_error(self, mock_temp, mock_info, mock_fetch,
                        mock_is_xen, mock_repl_xen, mock_copy, mock_convert,
                        mock_check_size):
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
        data.virtual_size = int(1234.5 * units.Gi)
        tmp = mock_temp.return_value.__enter__.return_value
        image_service.show.return_value = {'disk_format': 'raw'}

        mock_check_size.side_effect = exception.ImageUnacceptable(
            image_id='fake_image_id', reason='test')

        self.assertRaises(
            exception.ImageUnacceptable,
            image_utils.fetch_to_volume_format,
            ctxt, image_service, image_id, dest, volume_format, blocksize,
            user_id=user_id, project_id=project_id, size=size,
            run_as_root=run_as_root)

        image_service.show.assert_called_once_with(ctxt, image_id)
        mock_temp.assert_called_once_with(prefix='image_download_%s_' %
                                          image_id)
        mock_info.assert_has_calls([
            mock.call(tmp, force_share=False, run_as_root=run_as_root),
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
    @mock.patch('cinder.image.image_utils.is_xenserver_format',
                return_value=False)
    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.temporary_file')
    def test_qemu_img_parse_error(self, mock_temp, mock_info,
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
        image_service.show.return_value = {'disk_format': 'raw'}

        self.assertRaises(
            exception.ImageUnacceptable,
            image_utils.fetch_to_volume_format,
            ctxt, image_service, image_id, dest, volume_format, blocksize,
            user_id=user_id, project_id=project_id, size=size,
            run_as_root=run_as_root)

        image_service.show.assert_called_once_with(ctxt, image_id)
        mock_temp.assert_called_once_with(prefix='image_download_%s_' %
                                          image_id)
        mock_info.assert_has_calls([
            mock.call(tmp, force_share=False, run_as_root=run_as_root),
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
    @mock.patch('cinder.image.image_utils.is_xenserver_format',
                return_value=False)
    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.temporary_file')
    def test_backing_file_error(self, mock_temp, mock_info,
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
        image_service.show.return_value = {'disk_format': 'raw'}

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
        mock_temp.assert_called_once_with(prefix='image_download_%s_' %
                                          image_id)
        mock_info.assert_has_calls([
            mock.call(tmp, force_share=False, run_as_root=run_as_root),
            mock.call(tmp, run_as_root=run_as_root)])
        mock_fetch.assert_called_once_with(ctxt, image_service, image_id,
                                           tmp, user_id, project_id)
        self.assertFalse(mock_repl_xen.called)
        self.assertFalse(mock_copy.called)
        self.assertFalse(mock_convert.called)

    @mock.patch('cinder.image.image_utils.check_virtual_size')
    @mock.patch('cinder.image.image_utils.check_available_space')
    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.volume_utils.copy_volume')
    @mock.patch(
        'cinder.image.image_utils.replace_xenserver_image_with_coalesced_vhd')
    @mock.patch('cinder.image.image_utils.is_xenserver_format',
                return_value=True)
    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.temporary_file')
    def test_xenserver_to_vhd(self, mock_temp, mock_info,
                              mock_fetch, mock_is_xen, mock_repl_xen,
                              mock_copy, mock_convert, mock_check_space,
                              mock_check_size):
        ctxt = mock.sentinel.context
        disk_format = 'vhd'
        qemu_img_format = image_utils.QEMU_IMG_FORMAT_MAP[disk_format]
        image_service = FakeImageService(disk_format=disk_format)
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        volume_format = mock.sentinel.volume_format
        blocksize = mock.sentinel.blocksize
        ctxt.user_id = user_id = mock.sentinel.user_id
        project_id = mock.sentinel.project_id
        size = 4321
        run_as_root = mock.sentinel.run_as_root

        data = mock_info.return_value
        data.file_format = qemu_img_format
        data.backing_file = None
        data.virtual_size = 1234
        tmp = mock_temp.return_value.__enter__.return_value

        output = image_utils.fetch_to_volume_format(
            ctxt, image_service, image_id, dest, volume_format, blocksize,
            user_id=user_id, project_id=project_id, size=size,
            run_as_root=run_as_root)

        self.assertIsNone(output)
        mock_temp.assert_called_once_with(prefix='image_download_%s_' %
                                          image_id)
        mock_info.assert_has_calls([
            mock.call(tmp, force_share=False, run_as_root=run_as_root),
            mock.call(tmp, run_as_root=run_as_root)])
        mock_fetch.assert_called_once_with(ctxt, image_service, image_id,
                                           tmp, user_id, project_id)
        mock_repl_xen.assert_called_once_with(tmp)
        self.assertFalse(mock_copy.called)
        mock_convert.assert_called_once_with(tmp, dest, volume_format,
                                             out_subformat=None,
                                             run_as_root=run_as_root,
                                             src_format=qemu_img_format,
                                             image_id=image_id,
                                             data=data,
                                             disable_sparse=False)

    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info',
                side_effect=processutils.ProcessExecutionError)
    @mock.patch('cinder.image.image_utils.temporary_file')
    def test_no_qemu_img_fetch_verify_image(self,
                                            mock_temp, mock_info,
                                            mock_fetch):
        ctxt = mock.sentinel.context
        image_service = mock.Mock(temp_images=None)
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        ctxt.user_id = mock.sentinel.user_id

        image_service.show.return_value = {'disk_format': 'raw',
                                           'size': 41126400}

        image_utils.fetch_verify_image(
            ctxt, image_service, image_id, dest)

        image_service.show.assert_called_once_with(ctxt, image_id)
        mock_info.assert_called_once_with(dest,
                                          force_share=False,
                                          run_as_root=True)
        mock_fetch.assert_called_once_with(ctxt, image_service, image_id,
                                           dest, None, None)

    @mock.patch('cinder.image.image_utils.qemu_img_info',
                side_effect=processutils.ProcessExecutionError)
    @mock.patch('cinder.image.image_utils.temporary_file')
    def test_get_qemu_data_returns_none(self, mock_temp, mock_info):
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        run_as_root = mock.sentinel.run_as_root
        disk_format_raw = True
        has_meta = True

        output = image_utils.get_qemu_data(image_id, has_meta,
                                           disk_format_raw, dest,
                                           run_as_root=run_as_root)

        self.assertIsNone(output)

    @mock.patch('cinder.image.image_utils.qemu_img_info',
                side_effect=processutils.ProcessExecutionError)
    @mock.patch('cinder.image.image_utils.temporary_file')
    def test_get_qemu_data_with_image_meta_exception(self,
                                                     mock_temp, mock_info):
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        run_as_root = mock.sentinel.run_as_root
        disk_format_raw = False
        has_meta = True
        self.assertRaises(
            exception.ImageUnacceptable,
            image_utils.get_qemu_data, image_id, has_meta, disk_format_raw,
            dest, run_as_root=run_as_root)

    @mock.patch('cinder.image.image_utils.qemu_img_info',
                side_effect=processutils.ProcessExecutionError)
    @mock.patch('cinder.image.image_utils.temporary_file')
    def test_get_qemu_data_without_image_meta_except(self,
                                                     mock_temp, mock_info):
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        run_as_root = mock.sentinel.run_as_root

        disk_format_raw = False
        has_meta = False
        self.assertRaises(
            exception.ImageUnacceptable,
            image_utils.get_qemu_data, image_id, has_meta, disk_format_raw,
            dest, run_as_root=run_as_root)

    @mock.patch('cinder.image.accelerator.is_gzip_compressed',
                return_value = True)
    @mock.patch('cinder.image.accelerator.ImageAccel._get_engine')
    @mock.patch('cinder.image.accelerator.ImageAccel.is_engine_ready',
                return_value = True)
    @mock.patch('cinder.image.image_utils.check_available_space')
    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.volume_utils.copy_volume')
    @mock.patch(
        'cinder.image.image_utils.replace_xenserver_image_with_coalesced_vhd')
    @mock.patch('cinder.image.image_utils.is_xenserver_format',
                return_value=False)
    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.temporary_file')
    # FIXME: what 'defaults' are we talking about here?  By default
    # compression is not enabled!
    def test_defaults_compressed(self, mock_temp, mock_info,
                                 mock_fetch, mock_is_xen, mock_repl_xen,
                                 mock_copy, mock_convert, mock_check_space,
                                 mock_engine_ready, mock_get_engine,
                                 mock_gzip_compressed):
        class fakeEngine(object):
            def __init__(self):
                pass

            def decompress_img(self, src, dest, run_as_root):
                pass

        class FakeImageService(object):
            def __init__(self, image_service=None, disk_format='raw'):
                self.temp_images = None
                self.disk_format = disk_format

            def show(self, context, image_id):
                return {'size': 2 * units.Gi,
                        'disk_format': self.disk_format,
                        'container_format': 'compressed',
                        'status': 'active'}

        self.flags(allow_compression_on_image_upload=True)

        ctxt = mock.sentinel.context
        ctxt.user_id = mock.sentinel.user_id
        disk_format = 'ploop'
        qemu_img_format = image_utils.QEMU_IMG_FORMAT_MAP[disk_format]
        image_service = FakeImageService(disk_format=disk_format)
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        volume_format = mock.sentinel.volume_format
        out_subformat = None
        blocksize = mock.sentinel.blocksize

        data = mock_info.return_value
        data.file_format = qemu_img_format
        data.backing_file = None
        data.virtual_size = 1234
        tmp = mock_temp.return_value.__enter__.return_value

        mock_engine = mock.Mock(spec=fakeEngine)
        mock_get_engine.return_value = mock_engine

        output = image_utils.fetch_to_volume_format(ctxt, image_service,
                                                    image_id, dest,
                                                    volume_format, blocksize)

        self.assertIsNone(output)
        mock_temp.assert_called_once_with(prefix='image_download_%s_' %
                                          image_id)
        mock_info.assert_has_calls([
            mock.call(tmp, force_share=False, run_as_root=True),
            mock.call(tmp, run_as_root=True)])
        mock_fetch.assert_called_once_with(ctxt, image_service, image_id,
                                           tmp, None, None)
        self.assertFalse(mock_repl_xen.called)
        self.assertFalse(mock_copy.called)
        mock_convert.assert_called_once_with(tmp, dest, volume_format,
                                             out_subformat=out_subformat,
                                             run_as_root=True,
                                             src_format=qemu_img_format,
                                             image_id=image_id,
                                             data=data,
                                             disable_sparse=False)
        mock_engine.decompress_img.assert_called()


class TestXenserverUtils(test.TestCase):
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

    @mock.patch('cinder.image.image_utils.temporary_dir')
    @mock.patch('cinder.image.image_utils.coalesce_vhd')
    @mock.patch('cinder.image.image_utils.resize_vhd')
    @mock.patch('cinder.image.image_utils.get_vhd_size')
    @mock.patch('cinder.image.image_utils.utils.execute')
    def test_coalesce_chain(self, mock_exec, mock_size, mock_resize,
                            mock_coal, mock_temp):
        vhd_chain = (mock.sentinel.first,
                     mock.sentinel.second,
                     mock.sentinel.third,
                     mock.sentinel.fourth,
                     mock.sentinel.fifth)

        # os.path.join does not work with MagicMock objects on Windows.
        mock_temp.return_value.__enter__.return_value = 'fake_temp_dir'

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
    @mock.patch('cinder.image.image_utils.os.makedirs')
    @mock.patch('cinder.image.image_utils.tempfile.mkstemp')
    def test_create_temporary_file_no_dir(self, mock_mkstemp, mock_dirs,
                                          mock_close):
        self.flags(image_conversion_dir=None)
        fd = mock.sentinel.file_descriptor
        path = mock.sentinel.absolute_pathname
        mock_mkstemp.return_value = (fd, path)

        output = image_utils.create_temporary_file()

        self.assertEqual(path, output)
        mock_mkstemp.assert_called_once_with(dir=None)
        mock_close.assert_called_once_with(fd)

    @mock.patch('cinder.image.image_utils.os.close')
    @mock.patch('cinder.image.image_utils.os.makedirs')
    @mock.patch('cinder.image.image_utils.tempfile.mkstemp')
    def test_create_temporary_file_with_dir(self, mock_mkstemp, mock_dirs,
                                            mock_close):
        conv_dir = 'fake_conv_dir'
        self.flags(image_conversion_dir=conv_dir)
        fd = mock.sentinel.file_descriptor
        path = mock.sentinel.absolute_pathname
        mock_mkstemp.return_value = (fd, path)

        output = image_utils.create_temporary_file()

        self.assertEqual(path, output)
        self.assertTrue(mock_dirs.called)
        mock_mkstemp.assert_called_once_with(dir=conv_dir)
        mock_close.assert_called_once_with(fd)

    @mock.patch('cinder.image.image_utils.os.close')
    @mock.patch('cinder.image.image_utils.fileutils.ensure_tree')
    @mock.patch('cinder.image.image_utils.tempfile.mkstemp')
    def test_create_temporary_file_and_dir(self, mock_mkstemp, mock_dirs,
                                           mock_close):
        conv_dir = 'fake_conv_dir'
        self.flags(image_conversion_dir=conv_dir)
        fd = mock.sentinel.file_descriptor
        path = mock.sentinel.absolute_pathname
        mock_mkstemp.return_value = (fd, path)

        output = image_utils.create_temporary_file()

        self.assertEqual(path, output)
        mock_dirs.assert_called_once_with(conv_dir)
        mock_mkstemp.assert_called_once_with(dir=conv_dir)
        mock_close.assert_called_once_with(fd)

    @mock.patch('cinder.image.image_utils.os.remove')
    @mock.patch('cinder.image.image_utils.os.path.join')
    @mock.patch('cinder.image.image_utils.os.listdir')
    @mock.patch('cinder.image.image_utils.os.path.exists', return_value=True)
    def test_cleanup_temporary_file(self, mock_path, mock_listdir,
                                    mock_join, mock_remove):
        mock_listdir.return_value = ['tmphost@backend1', 'tmphost@backend2']
        conv_dir = 'fake_conv_dir'
        self.flags(image_conversion_dir=conv_dir)
        mock_join.return_value = '/test/tmp/tmphost@backend1'
        image_utils.cleanup_temporary_file('host@backend1')
        mock_listdir.assert_called_once_with(conv_dir)
        mock_remove.assert_called_once_with('/test/tmp/tmphost@backend1')

    @mock.patch('cinder.image.image_utils.os.remove')
    @mock.patch('cinder.image.image_utils.os.listdir')
    @mock.patch('cinder.image.image_utils.os.path.exists', return_value=False)
    def test_cleanup_temporary_file_with_not_exist_path(self, mock_path,
                                                        mock_listdir,
                                                        mock_remove):
        conv_dir = 'fake_conv_dir'
        self.flags(image_conversion_dir=conv_dir)
        image_utils.cleanup_temporary_file('host@backend1')
        self.assertFalse(mock_listdir.called)
        self.assertFalse(mock_remove.called)

    @mock.patch('cinder.image.image_utils.os.remove')
    @mock.patch('cinder.image.image_utils.os.path.join')
    @mock.patch('cinder.image.image_utils.os.listdir')
    @mock.patch('cinder.image.image_utils.os.path.exists', return_value=True)
    def test_cleanup_temporary_file_with_exception(self, mock_path,
                                                   mock_listdir,
                                                   mock_join, mock_remove):
        mock_listdir.return_value = ['tmphost@backend1', 'tmphost@backend2']
        conv_dir = 'fake_conv_dir'
        self.flags(image_conversion_dir=conv_dir)
        mock_join.return_value = '/test/tmp/tmphost@backend1'
        mock_remove.side_effect = OSError
        image_utils.cleanup_temporary_file('host@backend1')
        mock_listdir.assert_called_once_with(conv_dir)
        mock_remove.assert_called_once_with('/test/tmp/tmphost@backend1')


class TestTemporaryFileContextManager(test.TestCase):
    @mock.patch('cinder.image.image_utils.create_temporary_file',
                return_value=mock.sentinel.temporary_file)
    @mock.patch('cinder.image.image_utils.fileutils.delete_if_exists')
    def test_temporary_file(self, mock_delete, mock_create):
        with image_utils.temporary_file() as tmp_file:
            self.assertEqual(mock.sentinel.temporary_file, tmp_file)
            self.assertFalse(mock_delete.called)
        mock_delete.assert_called_once_with(mock.sentinel.temporary_file)


class TestImageUtils(test.TestCase):
    def test_get_virtual_size(self):
        image_id = fake.IMAGE_ID
        virtual_size = 1073741824
        volume_size = 2
        virt_size = image_utils.check_virtual_size(virtual_size,
                                                   volume_size,
                                                   image_id)
        self.assertEqual(1, virt_size)

    def test_get_bigger_virtual_size(self):
        image_id = fake.IMAGE_ID
        virtual_size = 3221225472
        volume_size = 2
        self.assertRaises(exception.ImageUnacceptable,
                          image_utils.check_virtual_size,
                          virtual_size,
                          volume_size,
                          image_id)

    def test_decode_cipher(self):
        expected = {'cipher_alg': 'aes-256',
                    'cipher_mode': 'xts',
                    'ivgen_alg': 'essiv'}
        result = image_utils.decode_cipher('aes-xts-essiv', 256)
        self.assertEqual(expected, result)

    def test_decode_cipher_invalid(self):
        self.assertRaises(exception.InvalidVolumeType,
                          image_utils.decode_cipher,
                          'aes',
                          256)


@ddt.ddt(testNameFormat=ddt.TestNameFormat.INDEX_ONLY)
class TestQcow2ImageChecks(test.TestCase):
    def setUp(self):
        super(TestQcow2ImageChecks, self).setUp()
        # Test data from:
        # $ qemu-img create -f qcow2 fake.qcow2 1M
        # $ qemu-img info -f qcow2 fake.qcow2 --output=json
        qemu_img_info = '''
        {
            "virtual-size": 1048576,
            "filename": "fake.qcow2",
            "cluster-size": 65536,
            "format": "qcow2",
            "actual-size": 200704,
            "format-specific": {
                "type": "qcow2",
                "data": {
                    "compat": "1.1",
                    "compression-type": "zlib",
                    "lazy-refcounts": false,
                    "refcount-bits": 16,
                    "corrupt": false,
                    "extended-l2": false
                }
            },
            "dirty-flag": false
        }'''
        self.qdata = imageutils.QemuImgInfo(qemu_img_info, format='json')

    def test_check_qcow2_image_no_problem(self):
        image_utils.check_qcow2_image(fake.IMAGE_ID, self.qdata)

    def test_check_qcow2_image_with_datafile(self):
        self.qdata.format_specific['data']['data-file'] = '/not/good'
        e = self.assertRaises(exception.ImageUnacceptable,
                              image_utils.check_qcow2_image,
                              fake.IMAGE_ID,
                              self.qdata)
        self.assertIn('not allowed to have a data file', str(e))

    def test_check_qcow2_image_with_backing_file(self):
        # qcow2 backing file is done as a separate check because
        # cinder has legitimate uses for a qcow2 with backing file
        self.qdata.backing_file = '/this/is/ok'
        image_utils.check_qcow2_image(fake.IMAGE_ID, self.qdata)

    def test_check_qcow2_image_no_barf_bad_data(self):
        # should never happen, but you never know ...
        del self.qdata.format_specific['data']
        e = self.assertRaises(exception.ImageUnacceptable,
                              image_utils.check_qcow2_image,
                              fake.IMAGE_ID,
                              self.qdata)
        self.assertIn('Cannot determine format-specific', str(e))
        self.qdata.format_specific = None
        e = self.assertRaises(exception.ImageUnacceptable,
                              image_utils.check_qcow2_image,
                              fake.IMAGE_ID,
                              self.qdata)
        self.assertIn('Cannot determine format-specific', str(e))


@ddt.ddt(testNameFormat=ddt.TestNameFormat.INDEX_ONLY)
class TestVmdkImageChecks(test.TestCase):
    def setUp(self):
        super(TestVmdkImageChecks, self).setUp()
        # Test data from:
        # $ qemu-img create -f vmdk fake.vmdk 1M -o subformat=monolithicSparse
        # $ qemu-img info -f vmdk --output=json fake.vmdk
        #
        # What qemu-img calls the "subformat" is called the "createType" in
        # vmware-speak and it's found at "/format-specific/data/create-type".
        qemu_img_info = '''
        {
            "virtual-size": 1048576,
            "filename": "fake.vmdk",
            "cluster-size": 65536,
            "format": "vmdk",
            "actual-size": 12288,
            "format-specific": {
                "type": "vmdk",
                "data": {
                    "cid": 1200165687,
                    "parent-cid": 4294967295,
                    "create-type": "monolithicSparse",
                    "extents": [
                        {
                            "virtual-size": 1048576,
                            "filename": "fake.vmdk",
                            "cluster-size": 65536,
                            "format": ""
                        }
                    ]
                }
            },
            "dirty-flag": false
        }'''
        self.qdata = imageutils.QemuImgInfo(qemu_img_info, format='json')
        self.qdata_data = self.qdata.format_specific['data']
        # we will populate this in each test
        self.qdata_data["create-type"] = None

    @ddt.data('monolithicSparse', 'streamOptimized')
    def test_check_vmdk_image_default_config(self, subformat):
        # none of these should raise
        self.qdata_data["create-type"] = subformat
        image_utils.check_vmdk_image(fake.IMAGE_ID, self.qdata)

    @ddt.data('monolithicFlat', 'twoGbMaxExtentFlat')
    def test_check_vmdk_image_negative_default_config(self, subformat):
        self.qdata_data["create-type"] = subformat
        self.assertRaises(exception.ImageUnacceptable,
                          image_utils.check_vmdk_image,
                          fake.IMAGE_ID,
                          self.qdata)

    def test_check_vmdk_image_handles_missing_info(self):
        expected = 'Unable to determine VMDK createType'
        # remove create-type
        del (self.qdata_data['create-type'])
        iue = self.assertRaises(exception.ImageUnacceptable,
                                image_utils.check_vmdk_image,
                                fake.IMAGE_ID,
                                self.qdata)
        self.assertIn(expected, str(iue))

        # remove entire data section
        del (self.qdata_data)
        iue = self.assertRaises(exception.ImageUnacceptable,
                                image_utils.check_vmdk_image,
                                fake.IMAGE_ID,
                                self.qdata)
        self.assertIn(expected, str(iue))

        # oslo.utils.imageutils guarantees that format_specific is
        # defined, so let's see what happens when it's empty
        self.qdata.format_specific = None
        iue = self.assertRaises(exception.ImageUnacceptable,
                                image_utils.check_vmdk_image,
                                fake.IMAGE_ID,
                                self.qdata)
        self.assertIn('no format-specific information is available', str(iue))

    def test_check_vmdk_image_positive(self):
        allowed = 'twoGbMaxExtentFlat'
        self.flags(vmdk_allowed_types=['garbage', allowed])
        self.qdata_data["create-type"] = allowed
        image_utils.check_vmdk_image(fake.IMAGE_ID, self.qdata)

    @ddt.data('monolithicSparse', 'streamOptimized')
    def test_check_vmdk_image_negative(self, subformat):
        allow_list = ['vmfs', 'filler']
        self.assertNotIn(subformat, allow_list)
        self.flags(vmdk_allowed_types=allow_list)
        self.qdata_data["create-type"] = subformat
        self.assertRaises(exception.ImageUnacceptable,
                          image_utils.check_vmdk_image,
                          fake.IMAGE_ID,
                          self.qdata)

    @ddt.data('monolithicSparse', 'streamOptimized', 'twoGbMaxExtentFlat')
    def test_check_vmdk_image_negative_empty_list(self, subformat):
        # anything should raise
        allow_list = []
        self.flags(vmdk_allowed_types=allow_list)
        self.qdata_data["create-type"] = subformat
        self.assertRaises(exception.ImageUnacceptable,
                          image_utils.check_vmdk_image,
                          fake.IMAGE_ID,
                          self.qdata)

    # OK, now that we know the function works properly, let's make sure
    # it's called in all the situations where Bug #1996188 indicates that
    # we need this check

    @mock.patch('cinder.image.image_utils.check_vmdk_image')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.fileutils')
    @mock.patch('cinder.image.image_utils.fetch')
    def test_vmdk_subformat_checked_fetch_verify_image(
            self, mock_fetch, mock_fileutils, mock_info, mock_check):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        mock_info.return_value = self.qdata
        mock_check.side_effect = exception.ImageUnacceptable(
            image_id=image_id, reason='mock check')

        iue = self.assertRaises(exception.ImageUnacceptable,
                                image_utils.fetch_verify_image,
                                ctxt, image_service, image_id, dest)
        self.assertIn('mock check', str(iue))
        mock_check.assert_called_with(image_id, self.qdata)

    @mock.patch('cinder.image.image_utils.check_vmdk_image')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.get_qemu_data')
    @mock.patch('cinder.image.image_utils.check_image_conversion_disable')
    def test_vmdk_subformat_checked_fetch_to_volume_format(
            self, mock_convert, mock_qdata, mock_info, mock_check):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_meta = {'disk_format': 'vmdk'}
        image_service.show.return_value = image_meta
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        volume_format = mock.sentinel.volume_format
        blocksize = 1024
        self.flags(allow_compression_on_image_upload=False)
        mock_qdata.return_value = self.qdata
        mock_info.return_value = self.qdata
        mock_check.side_effect = exception.ImageUnacceptable(
            image_id=image_id, reason='mock check')

        iue = self.assertRaises(exception.ImageUnacceptable,
                                image_utils.fetch_to_volume_format,
                                ctxt,
                                image_service,
                                image_id,
                                dest,
                                volume_format,
                                blocksize)
        self.assertIn('mock check', str(iue))
        mock_check.assert_called_with(image_id, self.qdata)

    @mock.patch('cinder.image.image_utils.check_vmdk_image')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.check_image_conversion_disable')
    def test_vmdk_subformat_checked_upload_volume(
            self, mock_convert, mock_info, mock_check):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_meta = {'disk_format': 'vmdk'}
        image_id = mock.sentinel.image_id
        image_meta['id'] = image_id
        self.flags(allow_compression_on_image_upload=False)
        mock_info.return_value = self.qdata
        mock_check.side_effect = exception.ImageUnacceptable(
            image_id=image_id, reason='mock check')

        iue = self.assertRaises(exception.ImageUnacceptable,
                                image_utils.upload_volume,
                                ctxt,
                                image_service,
                                image_meta,
                                volume_path=mock.sentinel.volume_path,
                                volume_format=mock.sentinel.volume_format)
        self.assertIn('mock check', str(iue))
        mock_check.assert_called_with(image_id, self.qdata)

    @mock.patch('cinder.image.image_utils.check_vmdk_image')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    def test_vmdk_checked_convert_image_no_src_format(
            self, mock_info, mock_check):
        source = mock.sentinel.source
        dest = mock.sentinel.dest
        out_format = mock.sentinel.out_format
        mock_info.return_value = self.qdata
        image_id = 'internal image'
        mock_check.side_effect = exception.ImageUnacceptable(
            image_id=image_id, reason='mock check')

        self.assertRaises(exception.ImageUnacceptable,
                          image_utils.convert_image,
                          source, dest, out_format)
        mock_check.assert_called_with(image_id, self.qdata)


@ddt.ddt(testNameFormat=ddt.TestNameFormat.INDEX_ONLY)
class TestImageFormatCheck(test.TestCase):
    def setUp(self):
        super(TestImageFormatCheck, self).setUp()
        qemu_img_info = '''
        {
            "virtual-size": 1048576,
            "filename": "whatever.img",
            "cluster-size": 65536,
            "format": "qcow2",
            "actual-size": 200704,
            "format-specific": {
                "type": "qcow2",
                "data": {
                    "compat": "1.1",
                    "compression-type": "zlib",
                    "lazy-refcounts": false,
                    "refcount-bits": 16,
                    "corrupt": false,
                    "extended-l2": false
                }
            },
            "dirty-flag": false
        }'''
        self.qdata = imageutils.QemuImgInfo(qemu_img_info, format='json')

    @mock.patch('cinder.image.image_utils.check_qcow2_image')
    @mock.patch('cinder.image.image_utils.check_vmdk_image')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    def test_check_image_format_defaults(self, mock_info, mock_vmdk,
                                         mock_qcow2):
        """Doesn't blow up when only the mandatory arg is passed."""
        src = mock.sentinel.src
        mock_info.return_value = self.qdata
        expected_image_id = 'internal image'

        # empty file_format should raise
        self.qdata.file_format = None
        iue = self.assertRaises(exception.ImageUnacceptable,
                                image_utils.check_image_format,
                                src)
        self.assertIn(expected_image_id, str(iue))
        mock_info.assert_called_with(src, run_as_root=True)

        # a VMDK should trigger an additional check
        mock_info.reset_mock()
        self.qdata.file_format = 'vmdk'
        image_utils.check_image_format(src)
        mock_vmdk.assert_called_with(expected_image_id, self.qdata)

        # Bug #2059809: a qcow2 should trigger an additional check
        mock_info.reset_mock()
        self.qdata.file_format = 'qcow2'
        image_utils.check_image_format(src)
        mock_qcow2.assert_called_with(expected_image_id, self.qdata)

    @mock.patch('cinder.image.image_utils.qemu_img_info')
    def test_check_image_format_uses_passed_data(self, mock_info):
        src = mock.sentinel.src
        image_utils.check_image_format(src, data=self.qdata)
        mock_info.assert_not_called()

    @mock.patch('cinder.image.image_utils.qemu_img_info')
    def test_check_image_format_mismatch(self, mock_info):
        src = mock.sentinel.src
        mock_info.return_value = self.qdata
        self.qdata.file_format = 'fake_format'

        src_format = 'qcow2'
        iue = self.assertRaises(exception.ImageUnacceptable,
                                image_utils.check_image_format,
                                src,
                                src_format=src_format)
        self.assertIn(src_format, str(iue))
        self.assertIn('different format', str(iue))

    @ddt.data('AMI', 'ami')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    def test_check_image_format_AMI(self, ami, mock_info):
        """Mismatch OK in this case, see change Icde4c0f936ce."""
        src = mock.sentinel.src
        mock_info.return_value = self.qdata
        self.qdata.file_format = 'raw'

        src_format = ami
        image_utils.check_image_format(src, src_format=src_format)

    @mock.patch('cinder.image.image_utils._convert_image')
    @mock.patch('cinder.image.image_utils.check_image_format')
    def test_check_image_format_called_by_convert_image(
            self, mock_check, mock__convert):
        """Make sure the function we've been testing is actually called."""
        src = mock.sentinel.src
        dest = mock.sentinel.dest
        out_fmt = mock.sentinel.out_fmt

        image_utils.convert_image(src, dest, out_fmt)
        mock_check.assert_called_once_with(src, None, None, None, True)


@ddt.ddt
class TestFilterReservedNamespaces(test.TestCase):

    def setUp(self):
        super(TestFilterReservedNamespaces, self).setUp()
        self.mock_object(image_utils, 'LOG', side_effect=image_utils.LOG)

    def test_filter_out_reserved_namespaces_metadata_with_empty_metadata(self):
        metadata_for_test = None
        method_return = image_utils.filter_out_reserved_namespaces_metadata(
            metadata_for_test)

        self.assertEqual({}, method_return)

        image_utils.LOG.debug.assert_has_calls(
            [mock.call("No metadata to be filtered.")]
        )

    @ddt.data(  # remove default keys
        ({"some_key": 13, "other_key": "test",
          "os_glance_key": "this should be removed",
          "os_glance_key2": "this should also be removed"},
         None,
         []),
        # remove nothing
        ({"some_key": 13, "other_key": "test"},
         None,
         []),
        # custom config empty
        ({"some_key": 13, "other_key": "test",
          "os_glance_key": "this should be removed",
          "os_glance_key2": "this should also be removed"},
         [],
         []),
        # custom config
        ({"some_key": 13, "other_key": "test",
          "os_glance_key": "this should be removed",
          "os_glance_key2": "this should also be removed",
          "custom_key": "this should be removed",
          "another_custom_key": "this should also be removed"},
         ['custom_key', 'another_custom_key'],
         ['custom_key', 'another_custom_key']))
    @ddt.unpack
    def test_filter_out_reserved_namespaces_metadata(
            self, metadata_for_test, config, keys_to_pop):
        hardcoded_keys = image_utils.GLANCE_RESERVED_NAMESPACES

        keys_to_pop = hardcoded_keys + keys_to_pop

        if config:
            self.override_config('reserved_image_namespaces', config)

        expected_result = {"some_key": 13, "other_key": "test"}

        method_return = image_utils.filter_out_reserved_namespaces_metadata(
            metadata_for_test)

        self.assertEqual(expected_result, method_return)

        image_utils.LOG.debug.assert_has_calls([
            mock.call("The metadata set [%s] was filtered using the reserved "
                      "name spaces [%s], and the result is [%s].",
                      metadata_for_test, keys_to_pop, expected_result)
        ])

    @ddt.data(  # remove default keys
        ({"some_key": 13, "other_key": "test",
          "os_glance_key": "this should be removed",
          "os_glance_key2": "this should also be removed",
          "properties": {"os_glance_key3": "this should be removed",
                         "os_glance_key4": "this should also be removed",
                         "another_key": "foobar"}
          },
         None,
         []),
        # remove nothing
        ({"some_key": 13, "other_key": "test",
          "properties": {"another_key": "foobar"}},
         None,
         []),
        # custom config empty
        ({"some_key": 13, "other_key": "test",
          "os_glance_key": "this should be removed",
          "os_glance_key2": "this should also be removed",
          "properties": {"os_glance_key3": "this should be removed",
                         "os_glance_key4": "this should also be removed",
                         "another_key": "foobar"}
          },
         [],
         []),
        # custom config
        ({"some_key": 13, "other_key": "test",
          "os_glance_key": "this should be removed",
          "os_glance_key2": "this should also be removed",
          "properties": {"os_glance_key3": "this should be removed",
                         "os_glance_key4": "this should also be removed",
                         "custom_key": "this should be removed",
                         "another_custom_key": "this should also be removed",
                         "another_key": "foobar"},
          },
         ['custom_key', 'another_custom_key'],
         ['custom_key', 'another_custom_key']))
    @ddt.unpack
    def test_filter_out_reserved_namespaces_metadata_properties(
            self, metadata_for_test, config, keys_to_pop):
        hardcoded_keys = image_utils.GLANCE_RESERVED_NAMESPACES

        keys_to_pop = hardcoded_keys + keys_to_pop

        if config:
            self.override_config('reserved_image_namespaces', config)

        expected_result = {
            "some_key": 13,
            "other_key": "test",
            "properties": {
                "another_key": "foobar"
            }
        }

        method_return = image_utils.filter_out_reserved_namespaces_metadata(
            metadata_for_test)

        self.assertEqual(expected_result, method_return)

        image_utils.LOG.debug.assert_has_calls([
            mock.call("The metadata set [%s] was filtered using the reserved "
                      "name spaces [%s], and the result is [%s].",
                      metadata_for_test, keys_to_pop, expected_result)
        ])
