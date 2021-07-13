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
from oslo_utils import units

from cinder import exception
from cinder.image import image_utils
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import test
from cinder.volume import throttling


class TestQemuImgInfo(test.TestCase):
    @mock.patch('os.name', new='posix')
    @mock.patch('oslo_utils.imageutils.QemuImgInfo')
    @mock.patch('cinder.utils.execute')
    def test_qemu_img_info(self, mock_exec, mock_info):
        mock_out = mock.sentinel.out
        mock_err = mock.sentinel.err
        test_path = mock.sentinel.path
        mock_exec.return_value = (mock_out, mock_err)

        output = image_utils.qemu_img_info(test_path)
        mock_exec.assert_called_once_with('env', 'LC_ALL=C', 'qemu-img',
                                          'info', test_path, run_as_root=True,
                                          prlimit=image_utils.QEMU_IMG_LIMITS)
        self.assertEqual(mock_info.return_value, output)

    @mock.patch('os.name', new='posix')
    @mock.patch('oslo_utils.imageutils.QemuImgInfo')
    @mock.patch('cinder.utils.execute')
    def test_qemu_img_info_not_root(self, mock_exec, mock_info):
        mock_out = mock.sentinel.out
        mock_err = mock.sentinel.err
        test_path = mock.sentinel.path
        mock_exec.return_value = (mock_out, mock_err)

        output = image_utils.qemu_img_info(test_path,
                                           force_share=False,
                                           run_as_root=False)
        mock_exec.assert_called_once_with('env', 'LC_ALL=C', 'qemu-img',
                                          'info', test_path, run_as_root=False,
                                          prlimit=image_utils.QEMU_IMG_LIMITS)
        self.assertEqual(mock_info.return_value, output)

    @mock.patch('cinder.image.image_utils.os')
    @mock.patch('oslo_utils.imageutils.QemuImgInfo')
    @mock.patch('cinder.utils.execute')
    def test_qemu_img_info_on_nt(self, mock_exec, mock_info, mock_os):
        mock_out = mock.sentinel.out
        mock_err = mock.sentinel.err
        test_path = mock.sentinel.path
        mock_exec.return_value = (mock_out, mock_err)
        mock_os.name = 'nt'

        output = image_utils.qemu_img_info(test_path)
        mock_exec.assert_called_once_with('qemu-img', 'info', test_path,
                                          run_as_root=True,
                                          prlimit=image_utils.QEMU_IMG_LIMITS)
        self.assertEqual(mock_info.return_value, output)

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
        mock_info.side_effect = ValueError
        throttle = throttling.Throttle(prefix=['cgcmd'])

        with mock.patch('cinder.volume.volume_utils.check_for_odirect_support',
                        return_value=True):
            output = image_utils.convert_image(source, dest, out_format,
                                               throttle=throttle)

            mock_info.assert_called_once_with(source, run_as_root=True)
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
        mock_info.side_effect = ValueError

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

    @mock.patch('cinder.image.image_utils.CONF')
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
                                         mock_odirect,
                                         mock_conf):
        source = mock.sentinel.source
        mock_conf.image_conversion_dir = 'fakedir'
        dest = [mock_conf.image_conversion_dir]
        out_format = mock.sentinel.out_format
        mock_info.side_effect = ValueError
        mock_exec.side_effect = processutils.ProcessExecutionError(
            stderr='No space left on device')
        self.assertRaises(processutils.ProcessExecutionError,
                          image_utils.convert_image,
                          source, dest, out_format)
        mock_log.assert_called_with('Insufficient free space on fakedir for'
                                    ' image conversion.')


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
    @mock.patch('cinder.image.image_utils.CONF')
    @mock.patch('oslo_utils.fileutils.ensure_tree')
    @mock.patch('cinder.image.image_utils.utils.tempdir')
    def test_conv_dir_exists(self, mock_tempdir, mock_make,
                             mock_conf):
        mock_conf.image_conversion_dir = mock.sentinel.conv_dir

        output = image_utils.temporary_dir()

        self.assertTrue(mock_make.called)
        mock_tempdir.assert_called_once_with(dir=mock.sentinel.conv_dir)
        self.assertEqual(output, mock_tempdir.return_value)

    @mock.patch('cinder.image.image_utils.CONF')
    @mock.patch('oslo_utils.fileutils.ensure_tree')
    @mock.patch('cinder.image.image_utils.utils.tempdir')
    def test_create_conv_dir(self, mock_tempdir, mock_make,
                             mock_conf):
        mock_conf.image_conversion_dir = mock.sentinel.conv_dir

        output = image_utils.temporary_dir()

        mock_make.assert_called_once_with(mock.sentinel.conv_dir)
        mock_tempdir.assert_called_once_with(dir=mock.sentinel.conv_dir)
        self.assertEqual(output, mock_tempdir.return_value)

    @mock.patch('cinder.image.image_utils.CONF')
    @mock.patch('oslo_utils.fileutils.ensure_tree')
    @mock.patch('cinder.image.image_utils.utils.tempdir')
    def test_no_conv_dir(self, mock_tempdir, mock_make,
                         mock_conf):
        mock_conf.image_conversion_dir = None

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
    @mock.patch('cinder.image.image_utils.CONF')
    @mock.patch('cinder.image.image_utils.open', new_callable=mock.mock_open)
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.os')
    def test_diff_format(self, image_format, mock_os, mock_temp, mock_convert,
                         mock_info, mock_open, mock_conf, mock_proxy):
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
                                             compress=do_compress)
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
    @mock.patch('cinder.image.image_utils.CONF')
    @mock.patch('cinder.image.image_utils.open', new_callable=mock.mock_open)
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.os')
    def test_same_format(self, mock_os, mock_temp, mock_convert, mock_info,
                         mock_open, mock_conf, mock_chown, mock_proxy):
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
    @mock.patch('cinder.image.image_utils.CONF')
    @mock.patch('cinder.image.image_utils.open', new_callable=mock.mock_open)
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.os')
    def test_same_format_compressed(self, mock_os, mock_temp, mock_convert,
                                    mock_info, mock_open, mock_conf,
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
        mock_conf.allow_compression_on_image_upload = True
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
                                             run_as_root=True)
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
    @mock.patch('cinder.image.image_utils.CONF')
    @mock.patch('cinder.image.image_utils.open', new_callable=mock.mock_open)
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.os')
    def test_same_format_on_nt(self, mock_os, mock_temp, mock_convert,
                               mock_info, mock_open, mock_conf, mock_chown,
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
    @mock.patch('cinder.image.image_utils.CONF')
    @mock.patch('cinder.image.image_utils.open', new_callable=mock.mock_open)
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.os')
    def test_same_format_on_nt_compressed(self, mock_os, mock_temp,
                                          mock_convert, mock_info,
                                          mock_open, mock_conf,
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
        mock_conf.allow_compression_on_image_upload = True
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
                                             run_as_root=True)
        mock_info.assert_called_with(temp_file, run_as_root=True)
        self.assertEqual(2, mock_info.call_count)
        mock_open.assert_called_once_with(temp_file, 'rb')
        mock_proxy.assert_called_once_with(
            mock_open.return_value.__enter__.return_value)
        image_service.update.assert_called_once_with(
            ctxt, image_meta['id'], {}, mock_proxy.return_value,
            store_id=None, base_image_ref=None)
        mock_engine.compress_img.assert_called()

    @mock.patch('cinder.image.image_utils.CONF')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.os')
    def test_convert_error(self, mock_os, mock_temp, mock_convert, mock_info,
                           mock_conf):
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
                                             compress=True)
        mock_info.assert_called_with(temp_file, run_as_root=True)
        self.assertEqual(2, mock_info.call_count)
        self.assertFalse(image_service.update.called)

    @mock.patch('eventlet.tpool.Proxy')
    @mock.patch('cinder.image.image_utils.utils.temporary_chown')
    @mock.patch('cinder.image.image_utils.CONF')
    @mock.patch('cinder.image.image_utils.open', new_callable=mock.mock_open)
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.os')
    def test_base_image_ref(self, mock_os, mock_temp, mock_convert, mock_info,
                            mock_open, mock_conf, mock_chown, mock_proxy):
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
                                              run_as_root=True)

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
                                              dest, 'raw', blocksize,
                                              user_id=None, project_id=None,
                                              size=None, run_as_root=True)

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
                                              run_as_root=run_as_root)


class FakeImageService(object):
    def __init__(self, image_service=None, disk_format='raw'):
        self.temp_images = None
        self.disk_format = disk_format

    def show(self, context, image_id):
        return {'size': 2 * units.Gi,
                'disk_format': self.disk_format,
                'container_format': 'bare',
                'status': 'active'}


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
    @mock.patch('cinder.image.image_utils.CONF')
    def test_defaults(self, mock_conf, mock_temp, mock_info, mock_fetch,
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

        data = mock_info.return_value
        data.file_format = volume_format
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
                                             src_format='raw')

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
    @mock.patch('cinder.image.image_utils.CONF')
    def test_kwargs(self, mock_conf, mock_temp, mock_info, mock_fetch,
                    mock_is_xen, mock_repl_xen, mock_copy, mock_convert,
                    mock_check_space, mock_check_size):
        ctxt = mock.sentinel.context
        image_service = FakeImageService()
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
        data.file_format = volume_format
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
                                             src_format='raw')
        mock_check_size.assert_called_once_with(data.virtual_size,
                                                size, image_id)

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
    @mock.patch('cinder.image.image_utils.CONF')
    def test_convert_from_vhd(self, mock_conf, mock_temp, mock_info,
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

        data = mock_info.return_value
        data.file_format = volume_format
        data.backing_file = None
        data.virtual_size = 1234
        tmp = mock_temp.return_value.__enter__.return_value
        image_service = FakeImageService(disk_format='vhd')
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
                                             src_format=expect_format)

    @mock.patch('cinder.image.image_utils.check_virtual_size')
    @mock.patch('cinder.image.image_utils.check_available_space')
    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.volume_utils.copy_volume')
    @mock.patch('cinder.image.image_utils.is_xenserver_format',
                return_value=False)
    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.CONF')
    def test_convert_from_iso(self, mock_conf, mock_temp, mock_info,
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

        data = mock_info.return_value
        data.file_format = volume_format
        data.backing_file = None
        data.virtual_size = 1234
        tmp = mock_temp.return_value.__enter__.return_value
        image_service = FakeImageService(disk_format='iso')
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
                                             src_format=expect_format)

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
    @mock.patch('cinder.image.image_utils.CONF')
    def test_temporary_images(self, mock_conf, mock_temp, mock_info,
                              mock_fetch, mock_repl_xen,
                              mock_copy, mock_convert):
        ctxt = mock.sentinel.context
        ctxt.user_id = mock.sentinel.user_id
        image_service = FakeImageService()
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        volume_format = mock.sentinel.volume_format
        out_subformat = None
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
                                             src_format='raw')

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
        mock_temp.assert_called_once_with(prefix='image_download_%s_' %
                                          image_id)
        mock_info.assert_called_once_with(tmp,
                                          force_share=False,
                                          run_as_root=run_as_root)
        self.assertFalse(mock_fetch.called)
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
    @mock.patch('cinder.image.image_utils.CONF')
    def test_size_error(self, mock_conf, mock_temp, mock_info, mock_fetch,
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
    @mock.patch('cinder.image.image_utils.CONF')
    def test_xenserver_to_vhd(self, mock_conf, mock_temp, mock_info,
                              mock_fetch, mock_is_xen, mock_repl_xen,
                              mock_copy, mock_convert, mock_check_space,
                              mock_check_size):
        ctxt = mock.sentinel.context
        image_service = FakeImageService()
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
                                             src_format='raw')

    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info',
                side_effect=processutils.ProcessExecutionError)
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.CONF')
    def test_no_qemu_img_fetch_verify_image(self, mock_conf,
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
    @mock.patch('cinder.image.image_utils.CONF')
    def test_get_qemu_data_returns_none(self, mock_conf, mock_temp, mock_info):
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
    @mock.patch('cinder.image.image_utils.CONF')
    def test_get_qemu_data_with_image_meta_exception(self, mock_conf,
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
    @mock.patch('cinder.image.image_utils.CONF')
    def test_get_qemu_data_without_image_meta_except(self, mock_conf,
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
    @mock.patch('cinder.image.image_utils.CONF')
    def test_defaults_compressed(self, mock_conf, mock_temp, mock_info,
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

        ctxt = mock.sentinel.context
        ctxt.user_id = mock.sentinel.user_id
        image_service = FakeImageService()
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        volume_format = mock.sentinel.volume_format
        out_subformat = None
        blocksize = mock.sentinel.blocksize

        data = mock_info.return_value
        data.file_format = volume_format
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
                                             src_format='raw')
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
    @mock.patch('cinder.image.image_utils.CONF')
    @mock.patch('cinder.image.image_utils.os.makedirs')
    @mock.patch('cinder.image.image_utils.tempfile.mkstemp')
    def test_create_temporary_file_no_dir(self, mock_mkstemp, mock_dirs,
                                          mock_conf, mock_close):
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
    @mock.patch('cinder.image.image_utils.os.makedirs')
    @mock.patch('cinder.image.image_utils.tempfile.mkstemp')
    def test_create_temporary_file_with_dir(self, mock_mkstemp, mock_dirs,
                                            mock_conf, mock_close):
        conv_dir = mock.sentinel.image_conversion_dir
        mock_conf.image_conversion_dir = conv_dir
        fd = mock.sentinel.file_descriptor
        path = mock.sentinel.absolute_pathname
        mock_mkstemp.return_value = (fd, path)

        output = image_utils.create_temporary_file()

        self.assertEqual(path, output)
        self.assertTrue(mock_dirs.called)
        mock_mkstemp.assert_called_once_with(dir=conv_dir)
        mock_close.assert_called_once_with(fd)

    @mock.patch('cinder.image.image_utils.os.close')
    @mock.patch('cinder.image.image_utils.CONF')
    @mock.patch('cinder.image.image_utils.fileutils.ensure_tree')
    @mock.patch('cinder.image.image_utils.tempfile.mkstemp')
    def test_create_temporary_file_and_dir(self, mock_mkstemp, mock_dirs,
                                           mock_conf, mock_close):
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

    @mock.patch('cinder.image.image_utils.os.remove')
    @mock.patch('cinder.image.image_utils.os.path.join')
    @mock.patch('cinder.image.image_utils.CONF')
    @mock.patch('cinder.image.image_utils.os.listdir')
    @mock.patch('cinder.image.image_utils.os.path.exists', return_value=True)
    def test_cleanup_temporary_file(self, mock_path, mock_listdir, mock_conf,
                                    mock_join, mock_remove):
        mock_listdir.return_value = ['tmphost@backend1', 'tmphost@backend2']
        conv_dir = mock.sentinel.image_conversion_dir
        mock_conf.image_conversion_dir = conv_dir
        mock_join.return_value = '/test/tmp/tmphost@backend1'
        image_utils.cleanup_temporary_file('host@backend1')
        mock_listdir.assert_called_once_with(conv_dir)
        mock_remove.assert_called_once_with('/test/tmp/tmphost@backend1')

    @mock.patch('cinder.image.image_utils.os.remove')
    @mock.patch('cinder.image.image_utils.os.listdir')
    @mock.patch('cinder.image.image_utils.CONF')
    @mock.patch('cinder.image.image_utils.os.path.exists', return_value=False)
    def test_cleanup_temporary_file_with_not_exist_path(self, mock_path,
                                                        mock_conf,
                                                        mock_listdir,
                                                        mock_remove):
        conv_dir = mock.sentinel.image_conversion_dir
        mock_conf.image_conversion_dir = conv_dir
        image_utils.cleanup_temporary_file('host@backend1')
        self.assertFalse(mock_listdir.called)
        self.assertFalse(mock_remove.called)

    @mock.patch('cinder.image.image_utils.os.remove')
    @mock.patch('cinder.image.image_utils.os.path.join')
    @mock.patch('cinder.image.image_utils.CONF')
    @mock.patch('cinder.image.image_utils.os.listdir')
    @mock.patch('cinder.image.image_utils.os.path.exists', return_value=True)
    def test_cleanup_temporary_file_with_exception(self, mock_path,
                                                   mock_listdir, mock_conf,
                                                   mock_join, mock_remove):
        mock_listdir.return_value = ['tmphost@backend1', 'tmphost@backend2']
        conv_dir = mock.sentinel.image_conversion_dir
        mock_conf.image_conversion_dir = conv_dir
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
