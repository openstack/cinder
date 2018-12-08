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
"""Tests for the base chunkedbackupdriver class."""

import json
import uuid

import mock
from oslo_config import cfg
from oslo_utils import units

from cinder.backup import chunkeddriver as cbd
from cinder import context
from cinder import exception
from cinder import objects
from cinder.objects import fields
from cinder import test


CONF = cfg.CONF

TEST_DATA = ('abcdefhijklmnopqrstuvwxyz' * 10).encode('utf-8')


class ConcreteChunkedDriver(cbd.ChunkedBackupDriver):
    def __init__(self, ctxt):
        super(ConcreteChunkedDriver, self).__init__(
            ctxt, 1, 1, 'container', False)

    def _generate_object_name_prefix(self, backup):
        return 'test-'

    def delete_object(self, container, object_name):
        return True

    def get_container_entries(self, container, prefix):
        return ['{}{}'.format(container, prefix)]

    def get_extra_metadata(self, backup, volume):
        return "{}extra_metadata".format(volume.id)

    def get_object_reader(self, *args, **kwargs):
        return TestObjectReader(*args, **kwargs)

    def get_object_writer(self, *args, **kwargs):
        return TestObjectWriter(self, *args, **kwargs)

    def put_container(self, bucket):
        pass

    def update_container_name(self, backup, bucket):
        return None


class TestObjectWriter(object):
    def __init__(self, container, filename, extra_metadata=None):
        self.container = container
        self.filename = filename
        self.extra_metadata = extra_metadata
        self.written_data = None
        self.write_count = 0

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        pass

    def write(self, data):
        self.written_data = data
        self.write_count += 1


class TestObjectReader(object):
    def __init__(self, container, filename, extra_metadata=None):
        self.container = container
        self.filename = filename
        self.extra_metadata = extra_metadata
        self.written_data = None
        metadata = {}
        metadata['version'] = 1
        metadata['backup_id'] = 'backupid'
        metadata['volume_id'] = 'volumeid'
        metadata['backup_name'] = 'backup_name'
        metadata['backup_description'] = 'backup_description'
        metadata['objects'] = ['obj1']
        metadata['parent_id'] = 'parent_id'
        metadata['extra_metadata'] = 'extra_metadata'
        metadata['chunk_size'] = 1
        metadata['sha256s'] = ['sha']
        metadata['volume_meta'] = json.dumps(metadata)
        metadata['version'] = '1.0.0'
        self.metadata = metadata

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        pass

    def read(self):
        return json.dumps(self.metadata).encode('utf-8')


class ChunkedDriverTestCase(test.TestCase):

    def _create_backup_db_entry(self, volume_id=str(uuid.uuid4()),
                                restore_volume_id=None,
                                display_name='test_backup',
                                display_description='this is a test backup',
                                container='volumebackups',
                                status=fields.BackupStatus.CREATING,
                                size=1,
                                object_count=0,
                                project_id=str(uuid.uuid4()),
                                service=None,
                                temp_volume_id=None,
                                temp_snapshot_id=None,
                                snapshot_id=None,
                                metadata=None,
                                parent_id=None,
                                encryption_key_id=None):
        """Create a backup entry in the DB.

        Return the entry ID
        """
        kwargs = {}
        kwargs['volume_id'] = volume_id
        kwargs['restore_volume_id'] = restore_volume_id
        kwargs['user_id'] = str(uuid.uuid4())
        kwargs['project_id'] = project_id
        kwargs['host'] = 'testhost'
        kwargs['availability_zone'] = '1'
        kwargs['display_name'] = display_name
        kwargs['display_description'] = display_description
        kwargs['container'] = container
        kwargs['status'] = status
        kwargs['fail_reason'] = ''
        kwargs['service'] = service or CONF.backup_driver
        kwargs['snapshot_id'] = snapshot_id
        kwargs['parent_id'] = parent_id
        kwargs['size'] = size
        kwargs['object_count'] = object_count
        kwargs['temp_volume_id'] = temp_volume_id
        kwargs['temp_snapshot_id'] = temp_snapshot_id
        kwargs['metadata'] = metadata or {}
        kwargs['encryption_key_id'] = encryption_key_id
        kwargs['service_metadata'] = 'test_metadata'
        backup = objects.Backup(context=self.ctxt, **kwargs)
        backup.create()
        return backup

    def _create_volume_db_entry(self, display_name='test_volume',
                                display_description='this is a test volume',
                                status='backing-up',
                                previous_status='available',
                                size=1,
                                host='testhost',
                                encryption_key_id=None):
        """Create a volume entry in the DB.

        Return the entry ID
        """
        vol = {}
        vol['size'] = size
        vol['host'] = host
        vol['user_id'] = str(uuid.uuid4())
        vol['project_id'] = str(uuid.uuid4())
        vol['status'] = status
        vol['display_name'] = display_name
        vol['display_description'] = display_description
        vol['attach_status'] = fields.VolumeAttachStatus.DETACHED
        vol['availability_zone'] = '1'
        vol['previous_status'] = previous_status
        vol['encryption_key_id'] = encryption_key_id
        volume = objects.Volume(context=self.ctxt, **vol)
        volume.create()
        return volume.id

    def setUp(self):
        super(ChunkedDriverTestCase, self).setUp()
        self.ctxt = context.get_admin_context()
        self.driver = ConcreteChunkedDriver(self.ctxt)
        self.driver.compressor = None
        self.volume = self._create_volume_db_entry()
        self.backup = self._create_backup_db_entry(volume_id=self.volume)

    def test_get_compressor_none(self):
        for algo in ['None', 'Off', 'No']:
            self.assertIsNone(self.driver._get_compressor(algo))

    def test_get_compressor_zlib(self):
        for algo in ['zlib', 'gzip']:
            self.assertTrue('zlib' in str(self.driver._get_compressor(algo)))

    def test_get_compressor_bz(self):
        for algo in ['bz2', 'bzip2']:
            self.assertTrue('bz' in str(self.driver._get_compressor(algo)))

    def test_get_compressor_invalid(self):
        self.assertRaises(ValueError, self.driver._get_compressor, 'winzip')

    def test_create_container(self):
        self.assertEqual(self.backup.container,
                         self.driver._create_container(self.backup))

    def test_create_container_default(self):
        self.backup.container = None
        self.assertEqual('container',
                         self.driver._create_container(self.backup))

    def test_create_container_new_container(self):
        with mock.patch.object(self.driver, 'update_container_name',
                               return_value='new_and_improved'):
            self.assertEqual('new_and_improved',
                             self.driver._create_container(self.backup))

    def test_generate_object_names(self):
        obj_names = self.driver._generate_object_names(self.backup)
        self.assertTrue(len(obj_names) == 1)
        self.assertEqual('{}{}'.format(self.backup.container,
                                       self.backup.service_metadata),
                         obj_names[0])

    def test_metadata_filename(self):
        filename = self.driver._metadata_filename(self.backup)
        self.assertEqual('{}_metadata'.format(self.backup.service_metadata),
                         filename)

    def test_sha256_filename(self):
        filename = self.driver._sha256_filename(self.backup)
        self.assertEqual('{}_sha256file'.format(self.backup.service_metadata),
                         filename)

    def test_write_metadata(self):
        obj_writer = TestObjectWriter('', '')
        with mock.patch.object(self.driver, 'get_object_writer',
                               return_value=obj_writer):
            self.driver._write_metadata(self.backup, 'volid', 'contain_name',
                                        ['obj1'], 'volume_meta',
                                        extra_metadata='extra_metadata')

            self.assertIsNotNone(obj_writer.written_data)
            written_data = obj_writer.written_data.decode('utf-8')
            metadata = json.loads(written_data)
            self.assertEqual(self.driver.DRIVER_VERSION,
                             metadata.get('version'))
            self.assertEqual(self.backup.id, metadata.get('backup_id'))
            self.assertEqual('volid', metadata.get('volume_id'))
            self.assertEqual(self.backup.display_name,
                             metadata.get('backup_name'))
            self.assertEqual(self.backup.display_description,
                             metadata.get('backup_description'))
            self.assertEqual(['obj1'], metadata.get('objects'))
            self.assertEqual(self.backup.parent_id, metadata.get('parent_id'))
            self.assertEqual('volume_meta', metadata.get('volume_meta'))
            self.assertEqual('extra_metadata', metadata.get('extra_metadata'))

    def test_write_sha256file(self):
        obj_writer = TestObjectWriter('', '')
        with mock.patch.object(self.driver, 'get_object_writer',
                               return_value=obj_writer):
            self.driver._write_sha256file(self.backup, 'volid', 'contain_name',
                                          ['sha'])

            self.assertIsNotNone(obj_writer.written_data)
            written_data = obj_writer.written_data.decode('utf-8')
            metadata = json.loads(written_data)
            self.assertEqual(self.driver.DRIVER_VERSION,
                             metadata.get('version'))
            self.assertEqual(self.backup.id, metadata.get('backup_id'))
            self.assertEqual('volid', metadata.get('volume_id'))
            self.assertEqual(self.backup.display_name,
                             metadata.get('backup_name'))
            self.assertEqual(self.backup.display_description,
                             metadata.get('backup_description'))
            self.assertEqual(self.driver.sha_block_size_bytes,
                             metadata.get('chunk_size'))
            self.assertEqual(['sha'], metadata.get('sha256s'))

    def test_read_metadata(self):
        obj_reader = TestObjectReader('', '')
        with mock.patch.object(self.driver, 'get_object_reader',
                               return_value=obj_reader):
            metadata = self.driver._read_metadata(self.backup)

            self.assertIsNotNone(obj_reader.metadata)
            expected = obj_reader.metadata
            self.assertEqual(expected['version'], metadata['version'])
            self.assertEqual(expected['backup_id'], metadata['backup_id'])
            self.assertEqual(expected['volume_id'], metadata['volume_id'])
            self.assertEqual(expected['backup_name'], metadata['backup_name'])
            self.assertEqual(expected['backup_description'],
                             metadata['backup_description'])
            self.assertEqual(expected['objects'], metadata['objects'])
            self.assertEqual(expected['parent_id'], metadata['parent_id'])
            self.assertEqual(expected['volume_meta'], metadata['volume_meta'])
            self.assertEqual(expected['extra_metadata'],
                             metadata['extra_metadata'])

    def test_read_sha256file(self):
        obj_reader = TestObjectReader('', '')
        with mock.patch.object(self.driver, 'get_object_reader',
                               return_value=obj_reader):
            metadata = self.driver._read_sha256file(self.backup)

            self.assertIsNotNone(obj_reader.metadata)
            expected = obj_reader.metadata
            self.assertEqual(expected['version'], metadata['version'])
            self.assertEqual(expected['backup_id'], metadata['backup_id'])
            self.assertEqual(expected['volume_id'], metadata['volume_id'])
            self.assertEqual(expected['backup_name'], metadata['backup_name'])
            self.assertEqual(expected['backup_description'],
                             metadata['backup_description'])
            self.assertEqual(expected['chunk_size'], metadata['chunk_size'])
            self.assertEqual(expected['sha256s'], metadata['sha256s'])

    def test_prepare_backup(self):
        (object_meta, object_sha256, extra_metadata, container,
         volume_size_bytes) = self.driver._prepare_backup(self.backup)

        self.assertDictEqual({'id': 1,
                              'list': [],
                              'prefix': 'test-',
                              'volume_meta': None,
                              'extra_metadata': "{}extra_metadata".format(
                                  self.volume),
                              },
                             object_meta)
        self.assertDictEqual({'id': 1,
                              'sha256s': [],
                              'prefix': 'test-',
                              },
                             object_sha256)
        self.assertEqual(extra_metadata, object_meta['extra_metadata'])
        self.assertEqual(self.backup.container, container)
        self.assertEqual(self.backup.size * units.Gi, volume_size_bytes)

    def test_prepare_backup_invalid_size(self):
        volume = self._create_volume_db_entry(size=0)
        backup = self._create_backup_db_entry(volume_id=volume)

        self.assertRaises(exception.InvalidVolume,
                          self.driver._prepare_backup,
                          backup)

    def test_backup_chunk(self):
        (object_meta, object_sha256, extra_metadata, container,
         volume_size_bytes) = self.driver._prepare_backup(self.backup)

        obj_writer = TestObjectWriter('', '')
        with mock.patch.object(self.driver, 'get_object_writer',
                               return_value=obj_writer):
            self.driver._backup_chunk(self.backup,
                                      self.backup.container,
                                      TEST_DATA,
                                      0,
                                      object_meta,
                                      extra_metadata)

        self.assertEqual(TEST_DATA, obj_writer.written_data)
        self.assertEqual(1, len(object_meta['list']))
        self.assertEqual(2, object_meta['id'])

        chunk = object_meta['list'][0]['test--00001']
        self.assertEqual('b4bc937908ab6be6039b6d4141200de8', chunk['md5'])
        self.assertEqual(0, chunk['offset'])
        self.assertEqual(len(TEST_DATA), chunk['length'])

    def test_finalize_backup(self):
        (object_meta, object_sha256, extra_metadata, container,
         volume_size_bytes) = self.driver._prepare_backup(self.backup)

        obj_writer = TestObjectWriter('', '')
        with mock.patch.object(self.driver, 'get_object_writer',
                               return_value=obj_writer):
            self.driver._backup_chunk(self.backup,
                                      self.backup.container,
                                      TEST_DATA,
                                      0,
                                      object_meta,
                                      extra_metadata)

            self.driver._finalize_backup(self.backup,
                                         self.backup.container,
                                         object_meta,
                                         object_sha256)

        self.assertEqual(1, self.backup.object_count)

    def test_backup_metadata(self):
        object_meta = {}

        self.driver._backup_metadata(self.backup, object_meta)
        self.assertTrue('volume_meta' in object_meta.keys())

        # Too much that we mostly don't care about for UT purposes. Just spot
        # check a few things
        metadata = json.loads(object_meta['volume_meta'])
        self.assertTrue('volume-base-metadata' in metadata.keys())
        self.assertEqual(self.volume, metadata['volume-base-metadata']['id'])
        self.assertEqual(1, metadata['volume-base-metadata']['size'])
        self.assertEqual('test_volume',
                         metadata['volume-base-metadata']['display_name'])
        self.assertEqual('testhost', metadata['volume-base-metadata']['host'])

    @mock.patch('cinder.volume.utils.notify_about_backup_usage')
    def test_send_progress_end(self, mock_notify):
        obj_meta = {}
        self.driver._send_progress_end(self.ctxt, self.backup, obj_meta)

        self.assertEqual(100, obj_meta.get('backup_percent', 0))
        self.assertTrue(mock_notify.called)

    @mock.patch('cinder.volume.utils.notify_about_backup_usage')
    def test_send_progress_notification(self, mock_notify):
        obj_meta = {}
        self.driver._send_progress_notification(
            self.ctxt, self.backup, obj_meta, 1, 2)

        self.assertEqual(50, obj_meta.get('backup_percent', 0))
        self.assertTrue(mock_notify.called)

    @mock.patch('cinder.tests.unit.fake_notifier.FakeNotifier._notify')
    def test_backup(self, mock_notify):
        volume_file = mock.Mock()
        volume_file.tell.side_effect = [0, len(TEST_DATA)]
        volume_file.read.side_effect = [TEST_DATA, b'']
        obj_writer = TestObjectWriter('', '')
        with mock.patch.object(self.driver, 'get_object_writer',
                               return_value=obj_writer):
            self.driver.backup(self.backup, volume_file)
        self.assert_notify_called(mock_notify,
                                  (['INFO', 'backup.createprogress'],))

    def test_backup_invalid_size(self):
        self.driver.chunk_size_bytes = 999
        self.driver.sha_block_size_bytes = 1024
        self.assertRaises(exception.InvalidBackup,
                          self.driver.backup,
                          self.backup,
                          mock.Mock())

    def test_restore(self):
        volume_file = mock.Mock()
        restore_test = mock.Mock()
        self.driver._restore_v1 = restore_test

        # Create a second backup
        backup = self._create_backup_db_entry(
            self.volume, parent_id=self.backup.id)

        with mock.patch.object(self.driver, 'put_metadata') as mock_put:
            self.driver.restore(backup, self.volume, volume_file)
            self.assertEqual(2, mock_put.call_count)

        restore_test.assert_called()

    def test_delete_backup(self):
        with mock.patch.object(self.driver, 'delete_object') as mock_delete:
            self.driver.delete_backup(self.backup)

        mock_delete.assert_called()
        self.assertEqual(1, mock_delete.call_count)
        mock_delete.assert_called_once_with(
            self.backup.container,
            self.backup.container + self.backup.service_metadata)
