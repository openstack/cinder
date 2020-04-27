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

from unittest import mock

from cinder import exception
from cinder.image import accelerator
from cinder.tests.unit import test


class TestAccelerators(test.TestCase):
    @mock.patch('cinder.utils.execute')
    @mock.patch('cinder.image.accelerators.qat.AccelQAT.is_accel_exist',
                return_value = True)
    @mock.patch('cinder.image.accelerators.gzip.AccelGZIP.is_accel_exist',
                return_value = True)
    # Compress test, QAT and GZIP available
    def test_compress_img_prefer_qat_when_available(self,
                                                    mock_gzip_exist,
                                                    mock_qat_exist,
                                                    mock_exec):

        source = 'fake_path'
        dest = 'fake_path'

        accel = accelerator.ImageAccel(source, dest)
        accel.compress_img(run_as_root=True)

        expected = [
            mock.call('qzip', '-k', dest, '-o', dest,
                      run_as_root=True),
            mock.call('mv', dest + '.gz', dest,
                      run_as_root=True)
        ]

        mock_exec.assert_has_calls(expected)

    @mock.patch('cinder.utils.execute')
    @mock.patch('cinder.image.accelerators.qat.AccelQAT.is_accel_exist',
                return_value = False)
    @mock.patch('cinder.image.accelerators.gzip.AccelGZIP.is_accel_exist',
                return_value = True)
    # Compress test, QAT not available but GZIP available
    def test_compress_img_qat_accel_not_exist_gzip_exist(self,
                                                         mock_gzip_exist,
                                                         mock_qat_exist,
                                                         mock_exec):
        source = 'fake_path'
        dest = 'fake_path'

        accel = accelerator.ImageAccel(source, dest)
        accel.compress_img(run_as_root=True)

        not_called = mock.call('qzip', '-k', dest, '-o', dest,
                               run_as_root=True)

        self.assertNotIn(not_called, mock_exec.call_args_list)

        expected = [
            mock.call('gzip', '-k', dest,
                      run_as_root=True),
            mock.call('mv', dest + '.gz', dest,
                      run_as_root=True)
        ]
        mock_exec.assert_has_calls(expected)

    @mock.patch('cinder.utils.execute')
    @mock.patch('cinder.image.accelerators.qat.AccelQAT.is_accel_exist',
                return_value = True)
    @mock.patch('cinder.image.accelerators.gzip.AccelGZIP.is_accel_exist',
                return_value = False)
    # Compress test, QAT available but GZIP not available
    def test_compress_img_prefer_qat_without_gzip(self,
                                                  mock_gzip_exist,
                                                  mock_qat_exist,
                                                  mock_exec):

        source = 'fake_path'
        dest = 'fake_path'

        accel = accelerator.ImageAccel(source, dest)
        accel.compress_img(run_as_root=True)

        expected = [
            mock.call('qzip', '-k', dest, '-o', dest,
                      run_as_root=True),
            mock.call('mv', dest + '.gz', dest,
                      run_as_root=True)
        ]

        mock_exec.assert_has_calls(expected)

    @mock.patch('cinder.utils.execute')
    @mock.patch('cinder.image.accelerators.qat.AccelQAT.is_accel_exist',
                return_value = False)
    @mock.patch('cinder.image.accelerators.gzip.AccelGZIP.is_accel_exist',
                return_value = False)
    # Compress test, no accelerator available
    def test_compress_img_no_accel_exist(self,
                                         mock_gzip_exist,
                                         mock_qat_exist,
                                         mock_exec):
        source = 'fake_path'
        dest = 'fake_path'

        self.assertRaises(exception.CinderException,
                          accelerator.ImageAccel,
                          source,
                          dest)

    @mock.patch('cinder.utils.execute')
    @mock.patch('cinder.image.accelerators.qat.AccelQAT.is_accel_exist',
                return_value = True)
    @mock.patch('cinder.image.accelerators.gzip.AccelGZIP.is_accel_exist',
                return_value = True)
    # Decompress test, QAT and GZIP available
    def test_decompress_img_prefer_qat_when_available(self,
                                                      mock_gzip_exist,
                                                      mock_qat_exist,
                                                      mock_exec):
        source = 'fake_path'
        dest = 'fake_path'

        accel = accelerator.ImageAccel(source, dest)
        accel.decompress_img(run_as_root=True)

        expected = [
            mock.call('mv', source, source + '.gz',
                      run_as_root=True),
            mock.call('qzip', '-d', source + '.gz',
                      run_as_root=True)
        ]

        mock_exec.assert_has_calls(expected)

    @mock.patch('cinder.utils.execute')
    @mock.patch('cinder.image.accelerators.qat.AccelQAT.is_accel_exist',
                return_value = False)
    @mock.patch('cinder.image.accelerators.gzip.AccelGZIP.is_accel_exist',
                return_value = True)
    # Decompress test, QAT not available but GZIP available
    def test_decompress_img_qat_accel_not_exist_gzip_exist(self,
                                                           mock_gzip_exist,
                                                           mock_qat_exist,
                                                           mock_exec):
        source = 'fake_path'
        dest = 'fake_path'

        accel = accelerator.ImageAccel(source, dest)
        accel.decompress_img(run_as_root=True)

        not_called = mock.call('qzip', '-d', source + '.gz',
                               run_as_root=True)

        self.assertNotIn(not_called, mock_exec.call_args_list)

        expected = [
            mock.call('mv', source, source + '.gz',
                      run_as_root=True),
            mock.call('gzip', '-d', source + '.gz',
                      run_as_root=True)
        ]

        mock_exec.assert_has_calls(expected)

    @mock.patch('cinder.utils.execute')
    @mock.patch('cinder.image.accelerators.qat.AccelQAT.is_accel_exist',
                return_value = True)
    @mock.patch('cinder.image.accelerators.gzip.AccelGZIP.is_accel_exist',
                return_value = False)
    # Decompress test, QAT available but GZIP not available
    def test_decompress_img_prefer_qat_without_gzip(self,
                                                    mock_gzip_exist,
                                                    mock_qat_exist,
                                                    mock_exec):
        source = 'fake_path'
        dest = 'fake_path'

        accel = accelerator.ImageAccel(source, dest)
        accel.decompress_img(run_as_root=True)

        expected = [
            mock.call('mv', source, source + '.gz',
                      run_as_root=True),
            mock.call('qzip', '-d', source + '.gz',
                      run_as_root=True)
        ]

        mock_exec.assert_has_calls(expected)

    @mock.patch('cinder.utils.execute')
    @mock.patch('cinder.image.accelerators.qat.AccelQAT.is_accel_exist',
                return_value = False)
    @mock.patch('cinder.image.accelerators.gzip.AccelGZIP.is_accel_exist',
                return_value = False)
    # Decompress test, no accelerator available
    def test_decompress_img_no_accel_exist(self,
                                           mock_gzip_exist,
                                           mock_qat_exist,
                                           mock_exec):
        source = 'fake_path'
        dest = 'fake_path'

        self.assertRaises(exception.CinderException,
                          accelerator.ImageAccel,
                          source,
                          dest)
