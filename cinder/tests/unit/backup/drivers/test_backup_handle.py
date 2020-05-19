# Copyright (C) 2020 SAP SE
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


from cinder.backup import chunkeddriver
from cinder import test
import mock


class BackupRestoreHandleV1TestCase(test.TestCase):

    BACKUP_RESTORE_HANDLE = chunkeddriver.BackupRestoreHandle

    def setUp(self):
        super(BackupRestoreHandleV1TestCase, self).setUp()
        self._driver = mock.Mock()
        self._volume_file = mock.Mock()
        self._volume_id = 'volume-01'
        self._obj = {
            'offset': 100,
            'length': 50,
            'container': 'obj_container',
            'name': 'obj_name',
            'backup_id': 'backup-1',
            'extra_metadata': {'foo': 'bar'},
            'compression': None
        }
        self._segment = chunkeddriver.Segment(self._obj)

    def test_add_object(self):
        obj1 = {'name': 'obj1', 'offset': 0, 'length': 100}
        obj2 = {'name': 'obj2', 'offset': 100, 'length': 100}
        # incremental
        obj3 = {'name': 'obj3', 'offset': 50, 'length': 100}
        obj4 = {'name': 'obj4', 'offset': 60, 'length': 50}
        handle = chunkeddriver.BackupRestoreHandleV1(self._driver,
                                                     self._volume_id,
                                                     self._volume_file)
        handle.add_object(obj1)
        handle.add_object(obj2)
        handle.add_object(obj3)
        handle.add_object(obj4)

        ranges = handle._segments

        self.assertEqual(0, ranges[0].offset)
        self.assertEqual(50, ranges[0].end)

        self.assertEqual(50, ranges[1].offset)
        self.assertEqual(60, ranges[1].end)

        self.assertEqual(60, ranges[2].offset)
        self.assertEqual(100, ranges[2].end)

        self.assertEqual(100, ranges[3].offset)
        self.assertEqual(110, ranges[3].end)

        self.assertEqual(110, ranges[4].offset)
        self.assertEqual(150, ranges[4].end)

        self.assertEqual(150, ranges[5].offset)
        self.assertEqual(200, ranges[5].end)

    @mock.patch.object(BACKUP_RESTORE_HANDLE, '_get_reader')
    @mock.patch.object(BACKUP_RESTORE_HANDLE, '_clear_reader')
    def test_read_segment(self, clear_reader, get_reader):
        buff_reader_mock = mock.Mock()
        buff_reader_mock.read.return_value = b"foo"
        get_reader.return_value = buff_reader_mock

        handle = chunkeddriver.BackupRestoreHandleV1(self._driver,
                                                     self._volume_id,
                                                     self._volume_file)
        data = handle._read_segment(self._segment)

        get_reader.assert_called_once_with(self._segment)
        buff_reader_mock.seek.assert_called_once_with(
            self._segment.offset - self._segment.obj['offset'])
        clear_reader.assert_called_once_with(self._segment)
        self.assertEqual(data, b"foo")

    @mock.patch.object(BACKUP_RESTORE_HANDLE, '_get_new_reader')
    def test_get_reader(self, get_new_reader):
        new_reader = mock.Mock()
        get_new_reader.return_value = new_reader
        handle = chunkeddriver.BackupRestoreHandleV1(self._driver,
                                                     self._volume_id,
                                                     self._volume_file)
        handle._get_reader(self._segment)
        get_new_reader.assert_called_once_with(self._segment)
        self.assertEqual(handle._object_readers, {
            self._segment.obj['name']: new_reader
        })

    @mock.patch.object(BACKUP_RESTORE_HANDLE, '_get_raw_bytes')
    def test_get_new_reader(self, get_raw_bytes):
        raw_bytes = b'data'
        get_raw_bytes.return_value = raw_bytes
        obj_reader = mock.Mock()
        get_obj_reader = mock.Mock()
        get_obj_reader.__enter__ = mock.Mock(return_value=obj_reader)
        get_obj_reader.__exit__ = mock.Mock(return_value=False)
        self._driver._get_object_reader.return_value = get_obj_reader
        handle = chunkeddriver.BackupRestoreHandleV1(self._driver,
                                                     self._volume_id,
                                                     self._volume_file)
        bytes_io = handle._get_new_reader(self._segment)
        self._driver._get_object_reader.assert_called_once_with(
            self._segment.obj['container'],
            self._segment.obj['name'],
            extra_metadata=self._segment.obj['extra_metadata'])
        get_raw_bytes.assert_called_once_with(obj_reader, self._segment.obj)
        self.assertEqual(bytes_io.getvalue(), raw_bytes)

    def test_get_raw_bytes(self, decompress=False):
        compressor = None
        obj = self._obj.copy()
        if decompress:
            compressor = mock.Mock()
            obj['compression'] = 'zlib'
        reader = mock.Mock()
        reader_ret = mock.Mock()
        reader.read.return_value = reader_ret
        self._driver._get_compressor.return_value = compressor

        handle = chunkeddriver.BackupRestoreHandleV1(self._driver,
                                                     self._volume_id,
                                                     self._volume_file)
        handle._get_raw_bytes(reader, obj)

        self._driver._get_compressor.\
            assert_called_once_with(obj['compression'])
        reader.read.assert_called_once_with()

        if decompress:
            compressor.decompress.assert_called_once_with(reader_ret)

    def test_get_raw_bytes_decompressed(self):
        self.test_get_raw_bytes(decompress=True)

    def test_clear_reader(self):
        obj_reader = mock.Mock()
        obj = self._obj.copy()
        obj['name'] = 'obj_name_2'
        obj_readers = {self._obj['name']: obj_reader}
        obj_readers_mock = mock.MagicMock()
        obj_readers_mock.__getitem__.side_effect = obj_readers.__getitem__

        handle = chunkeddriver.BackupRestoreHandleV1(self._driver,
                                                     self._volume_id,
                                                     self._volume_file)
        handle._object_readers = obj_readers_mock
        handle._segments = [self._segment,
                            chunkeddriver.Segment(obj),
                            chunkeddriver.Segment(self._obj)]

        handle._idx = 0
        handle._clear_reader(self._segment)
        obj_readers_mock.__getitem__.assert_not_called()
        obj_reader.close.assert_not_called()

        handle._idx = 1
        handle._clear_reader(self._segment)
        obj_readers_mock.__getitem__.assert_not_called()
        obj_reader.close.assert_not_called()

        handle._idx = 2
        handle._clear_reader(self._segment)
        obj_readers_mock.__getitem__.assert_called_once_with(self._obj['name'])
        obj_reader.close.assert_called_once_with()

    @mock.patch.object(BACKUP_RESTORE_HANDLE, '_read_segment')
    def test_finish_restore(self, read_segment):
        segment_bytes = b'foo'
        read_segment.return_value = segment_bytes
        file_handle = mock.Mock()
        file_handle.fileno.side_effect = IOError
        handle = chunkeddriver.BackupRestoreHandleV1(self._driver,
                                                     self._volume_id,
                                                     file_handle)
        handle._segments = [self._segment]

        handle.finish_restore()

        read_segment.assert_called_once_with(self._segment)
        file_handle.write.assert_called_once_with(segment_bytes)
        file_handle.fileno.assert_called_once_with()
        self.assertEqual(handle._idx, 0)
