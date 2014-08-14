# Copyright (c) 2014 VMware, Inc.
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

"""
Unit tests for image transfer utility classes.
"""

import math

from eventlet import greenthread
import mock

from cinder import test
from cinder.volume.drivers.vmware import error_util
from cinder.volume.drivers.vmware import io_util


class ThreadSafePipeTest(test.TestCase):
    """Tests for ThreadSafePipe."""

    def test_read(self):
        max_size = 10
        chunk_size = 10
        max_transfer_size = 30
        queue = io_util.ThreadSafePipe(max_size, max_transfer_size)

        def get_side_effect():
            return [1] * chunk_size

        queue.get = mock.Mock(side_effect=get_side_effect)
        while True:
            data_item = queue.read(chunk_size)
            if not data_item:
                break

        self.assertEqual(max_transfer_size, queue.transferred)
        exp_calls = [mock.call()] * int(math.ceil(float(max_transfer_size) /
                                                  chunk_size))
        self.assertEqual(exp_calls, queue.get.call_args_list)

    def test_write(self):
        queue = io_util.ThreadSafePipe(10, 30)
        queue.put = mock.Mock()
        write_count = 10
        for _ in range(0, write_count):
            queue.write([1])
        exp_calls = [mock.call([1])] * write_count
        self.assertEqual(exp_calls, queue.put.call_args_list)

    def test_seek(self):
        queue = io_util.ThreadSafePipe(10, 30)
        self.assertRaises(IOError, queue.seek, 0)

    def test_tell(self):
        max_transfer_size = 30
        queue = io_util.ThreadSafePipe(10, 30)
        self.assertEqual(max_transfer_size, queue.tell())


class GlanceWriteThreadTest(test.TestCase):
    """Tests for GlanceWriteThread class."""

    def _create_image_writer(self):
        self._image_service = mock.Mock()
        self._context = mock.Mock()
        self._input_file = mock.Mock()
        self._image_id = mock.Mock()
        return io_util.GlanceWriteThread(self._context, self._input_file,
                                         self._image_service, self._image_id)

    @mock.patch.object(greenthread, 'sleep')
    def test_start(self, mock_sleep):
        writer = self._create_image_writer()
        status_list = ['queued', 'saving', 'active']

        def image_service_show_side_effect(context, image_id):
            status = status_list.pop(0)
            return {'status': status}

        self._image_service.show.side_effect = image_service_show_side_effect
        exp_calls = [mock.call(self._context,
                               self._image_id)] * len(status_list)

        writer.start()
        self.assertTrue(writer.wait())
        self._image_service.update.assert_called_once_with(
            self._context, self._image_id, {}, data=self._input_file)
        self.assertEqual(exp_calls, self._image_service.show.call_args_list)

    def test_start_with_killed_status(self):
        writer = self._create_image_writer()

        def image_service_show_side_effect(_context, _image_id):
            return {'status': 'killed'}

        self._image_service.show.side_effect = image_service_show_side_effect

        writer.start()
        self.assertRaises(error_util.ImageTransferException, writer.wait)
        self._image_service.update.assert_called_once_with(
            self._context, self._image_id, {}, data=self._input_file)
        self._image_service.show.assert_called_once_with(self._context,
                                                         self._image_id)

    def test_start_with_unknown_status(self):
        writer = self._create_image_writer()

        def image_service_show_side_effect(_context, _image_id):
            return {'status': 'unknown'}

        self._image_service.show.side_effect = image_service_show_side_effect

        writer.start()
        self.assertRaises(error_util.ImageTransferException, writer.wait)
        self._image_service.update.assert_called_once_with(
            self._context, self._image_id, {}, data=self._input_file)
        self._image_service.show.assert_called_once_with(self._context,
                                                         self._image_id)

    def test_start_with_image_service_update_exception(self):
        writer = self._create_image_writer()
        self._image_service.update.side_effect = Exception

        writer.start()
        self.assertRaises(error_util.ImageTransferException, writer.wait)
        self._image_service.update.assert_called_once_with(
            self._context, self._image_id, {}, data=self._input_file)
        self.assertFalse(self._image_service.show.called)

    def test_start_with_image_service_show_exception(self):
        writer = self._create_image_writer()
        self._image_service.show.side_effect = Exception

        writer.start()
        self.assertRaises(error_util.ImageTransferException, writer.wait)
        self._image_service.update.assert_called_once_with(
            self._context, self._image_id, {}, data=self._input_file)
        self._image_service.show.assert_called_once_with(self._context,
                                                         self._image_id)
