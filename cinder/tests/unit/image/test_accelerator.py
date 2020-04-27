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

from cinder.image import accelerator
from cinder.tests.unit import test


class fakeEngine(object):

    def __init__(self):
        pass

    def compress_img(self, src, dest, run_as_root):
        pass

    def decompress_img(self, src, dest, run_as_root):
        pass


class TestAccelerator(test.TestCase):

    @mock.patch('cinder.image.accelerator.ImageAccel._get_engine')
    @mock.patch('cinder.image.accelerator.ImageAccel.is_engine_ready',
                return_value = True)
    def test_compress_img_engine_ready(self, mock_accel_engine_ready,
                                       mock_get_engine):
        source = mock.sentinel.source
        dest = mock.sentinel.dest
        run_as_root = mock.sentinel.run_as_root

        mock_engine = mock.Mock(spec=fakeEngine)
        mock_get_engine.return_value = mock_engine
        accel = accelerator.ImageAccel(source, dest)

        accel.compress_img(run_as_root=run_as_root)
        mock_engine.compress_img.assert_called()

    @mock.patch('cinder.image.accelerator.ImageAccel._get_engine')
    @mock.patch('cinder.image.accelerator.ImageAccel.is_engine_ready',
                return_value = False)
    def test_compress_img_engine_not_ready(self, mock_accel_engine_ready,
                                           mock_get_engine):

        source = mock.sentinel.source
        dest = mock.sentinel.dest
        run_as_root = mock.sentinel.run_as_root

        mock_engine = mock.Mock(spec=fakeEngine)
        mock_get_engine.return_value = mock_engine
        accel = accelerator.ImageAccel(source, dest)

        accel.compress_img(run_as_root=run_as_root)
        mock_engine.compress_img.assert_not_called()

    @mock.patch('cinder.image.accelerator.ImageAccel._get_engine')
    @mock.patch('cinder.image.accelerator.ImageAccel.is_engine_ready',
                return_value = True)
    def test_decompress_img_engine_ready(self, mock_accel_engine_ready,
                                         mock_get_engine):

        source = mock.sentinel.source
        dest = mock.sentinel.dest
        run_as_root = mock.sentinel.run_as_root

        mock_engine = mock.Mock(spec=fakeEngine)
        mock_get_engine.return_value = mock_engine
        accel = accelerator.ImageAccel(source, dest)

        accel.decompress_img(run_as_root=run_as_root)
        mock_engine.decompress_img.assert_called()

    @mock.patch('cinder.image.accelerator.ImageAccel._get_engine')
    @mock.patch('cinder.image.accelerator.ImageAccel.is_engine_ready',
                return_value = False)
    def test_decompress_img_engine_not_ready(self, mock_accel_engine_ready,
                                             mock_get_engine):

        source = mock.sentinel.source
        dest = mock.sentinel.dest
        run_as_root = mock.sentinel.run_as_root

        mock_engine = mock.Mock(spec=fakeEngine)
        mock_get_engine.return_value = mock_engine
        accel = accelerator.ImageAccel(source, dest)

        accel.decompress_img(run_as_root=run_as_root)
        mock_engine.decompress_img.assert_not_called()
