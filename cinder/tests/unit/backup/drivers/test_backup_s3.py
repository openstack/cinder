# Copyright (C) 2020 leafcloud b.v.
# Copyright (C) 2020 FUJITSU LIMITED
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
"""Tests for Backup s3 code."""

import bz2
import filecmp
import hashlib
import os
import shutil
import tempfile
import threading
from unittest import mock
import zlib

from eventlet import tpool
from moto import mock_s3
from oslo_utils import units

from cinder.backup.drivers import s3 as s3_dr
from cinder import context
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder.tests.unit.backup import fake_s3_client
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import test


class FakeMD5(object):
    def __init__(self, *args, **kwargs):
        pass

    @classmethod
    def digest(cls):
        return 's3cindermd5'.encode('utf-8')

    @classmethod
    def hexdigest(cls):
        return 's3cindermd5'


def s3_client(func):
    @mock.patch.object(s3_dr.boto3, 'client',
                       fake_s3_client.FakeS3Boto3.Client)
    @mock.patch.object(hashlib, 'md5', FakeMD5)
    def func_wrapper(self, *args, **kwargs):
        return func(self, *args, **kwargs)

    return func_wrapper


def fake_backup_metadata(self, backup, object_meta):
    raise exception.BackupDriverException(reason=_('fake'))


def fake_delete(self, backup):
    raise exception.BackupOperationError()


def _fake_delete_object(self, bucket_name, object_name):
    raise AssertionError('delete_object method should not be called.')


class BackupS3TestCase(test.TestCase):
    """Test Case for s3."""

    _DEFAULT_VOLUME_ID = 'c7eb81f4-bec6-4730-a60f-8888885874df'

    def _create_volume_db_entry(self, volume_id=_DEFAULT_VOLUME_ID):
        vol = {'id': volume_id,
               'size': 1,
               'status': 'available',
               'volume_type_id': self.vt['id']}
        return db.volume_create(self.ctxt, vol)['id']

    def _create_backup_db_entry(self,
                                volume_id=_DEFAULT_VOLUME_ID,
                                container=s3_dr.CONF.backup_s3_store_bucket,
                                parent_id=None,
                                status=None,
                                service_metadata=None):

        try:
            db.volume_get(self.ctxt, volume_id)
        except exception.NotFound:
            self._create_volume_db_entry(volume_id=volume_id)

        kwargs = {'size': 1,
                  'container': container,
                  'volume_id': volume_id,
                  'parent_id': parent_id,
                  'user_id': fake.USER_ID,
                  'project_id': fake.PROJECT_ID,
                  'status': status,
                  'service_metadata': service_metadata,
                  }
        backup = objects.Backup(context=self.ctxt, **kwargs)
        backup.create()
        return backup

    def _write_effective_compression_file(self, data_size):
        """Ensure file contents can be effectively compressed."""
        self.volume_file.seek(0)
        self.volume_file.write(bytes([65] * data_size))
        self.volume_file.seek(0)

    def setUp(self):
        super(BackupS3TestCase, self).setUp()
        self.ctxt = context.get_admin_context()
        self.volume_file = tempfile.NamedTemporaryFile()
        self.temp_dir = tempfile.mkdtemp()
        self.addCleanup(self.volume_file.close)
        # Remove tempdir.
        self.addCleanup(shutil.rmtree, self.temp_dir)
        self.size_volume_file = 0
        for _i in range(0, 64):
            self.volume_file.write(os.urandom(units.Ki))
            self.size_volume_file += 1024
        notify_patcher = mock.patch(
            'cinder.volume.volume_utils.notify_about_backup_usage')
        notify_patcher.start()
        self.addCleanup(notify_patcher.stop)
        self.flags(backup_s3_endpoint_url=None)
        self.flags(backup_s3_store_access_key='s3cinderaccesskey')
        self.flags(backup_s3_store_secret_key='s3cindersecretkey')
        self.flags(backup_s3_sse_customer_key='s3aeskey')

    @mock_s3
    def test_backup_correctly_configured(self):
        self.service = s3_dr.S3BackupDriver(self.ctxt)
        self.assertIsInstance(self.service, s3_dr.S3BackupDriver)

    @mock_s3
    def test_backup(self):
        volume_id = 'b09b1ad4-5f0e-4d3f-8b9e-0000004f5ec2'
        container_name = 'test-bucket'
        backup = self._create_backup_db_entry(volume_id=volume_id,
                                              container=container_name)
        service = s3_dr.S3BackupDriver(self.ctxt)
        self.volume_file.seek(0)
        result = service.backup(backup, self.volume_file)
        self.assertIsNone(result)

    @mock_s3
    def test_backup_uncompressed(self):
        volume_id = '2b9f10a3-42b4-4fdf-b316-000000ceb039'
        backup = self._create_backup_db_entry(volume_id=volume_id)
        self.flags(backup_compression_algorithm='none')
        service = s3_dr.S3BackupDriver(self.ctxt)
        self.volume_file.seek(0)
        service.backup(backup, self.volume_file)

    @mock_s3
    def test_backup_bz2(self):
        volume_id = 'dc0fee35-b44e-4f13-80d6-000000e1b50c'
        backup = self._create_backup_db_entry(volume_id=volume_id)
        self.flags(backup_compression_algorithm='bz2')
        service = s3_dr.S3BackupDriver(self.ctxt)
        self._write_effective_compression_file(self.size_volume_file)
        service.backup(backup, self.volume_file)

    @mock_s3
    def test_backup_zlib(self):
        volume_id = '5cea0535-b6fb-4531-9a38-000000bea094'
        backup = self._create_backup_db_entry(volume_id=volume_id)
        self.flags(backup_compression_algorithm='zlib')
        service = s3_dr.S3BackupDriver(self.ctxt)
        self._write_effective_compression_file(self.size_volume_file)
        service.backup(backup, self.volume_file)

    @mock_s3
    def test_backup_zstd(self):
        volume_id = '471910a0-a197-4259-9c50-0fc3d6a07dbc'
        backup = self._create_backup_db_entry(volume_id=volume_id)
        self.flags(backup_compression_algorithm='zstd')
        service = s3_dr.S3BackupDriver(self.ctxt)
        self._write_effective_compression_file(self.size_volume_file)
        service.backup(backup, self.volume_file)

    @mock_s3
    def test_backup_default_container(self):
        volume_id = '9552017f-c8b9-4e4e-a876-00000053349c'
        backup = self._create_backup_db_entry(volume_id=volume_id,
                                              container=None)
        service = s3_dr.S3BackupDriver(self.ctxt)
        self.volume_file.seek(0)
        service.backup(backup, self.volume_file)
        self.assertEqual('volumebackups', backup.container)

    @mock_s3
    def test_backup_custom_container(self):
        volume_id = '1da9859e-77e5-4731-bd58-000000ca119e'
        container_name = 'fake99'
        backup = self._create_backup_db_entry(volume_id=volume_id,
                                              container=container_name)
        service = s3_dr.S3BackupDriver(self.ctxt)
        self.volume_file.seek(0)
        service.backup(backup, self.volume_file)
        self.assertEqual(container_name, backup.container)

    @mock_s3
    def test_backup_shafile(self):
        volume_id = '6465dad4-22af-48f7-8a1a-000000218907'

        backup = self._create_backup_db_entry(volume_id=volume_id)
        service = s3_dr.S3BackupDriver(self.ctxt)
        self.volume_file.seek(0)
        service.backup(backup, self.volume_file)

        # Verify sha contents
        content1 = service._read_sha256file(backup)
        self.assertEqual(64 * units.Ki / content1['chunk_size'],
                         len(content1['sha256s']))

    @mock_s3
    def test_backup_cmp_shafiles(self):
        volume_id = '1a99ac67-c534-4fe3-b472-0000001785e2'

        backup = self._create_backup_db_entry(volume_id=volume_id)
        service1 = s3_dr.S3BackupDriver(self.ctxt)
        self.volume_file.seek(0)
        service1.backup(backup, self.volume_file)

        # Create incremental backup with no change to contents
        deltabackup = self._create_backup_db_entry(volume_id=volume_id,
                                                   container=None,
                                                   parent_id=backup.id)
        service2 = s3_dr.S3BackupDriver(self.ctxt)
        self.volume_file.seek(0)
        service2.backup(deltabackup, self.volume_file)

        # Compare shas from both files
        content1 = service1._read_sha256file(backup)
        content2 = service2._read_sha256file(deltabackup)

        self.assertEqual(len(content1['sha256s']), len(content2['sha256s']))
        self.assertEqual(set(content1['sha256s']), set(content2['sha256s']))

    @mock_s3
    def test_backup_delta_two_objects_change(self):
        volume_id = '30dab288-265a-4583-9abe-000000d42c67'

        self.flags(backup_s3_object_size=8 * units.Ki)
        self.flags(backup_s3_block_size=units.Ki)

        backup = self._create_backup_db_entry(volume_id=volume_id)
        service1 = s3_dr.S3BackupDriver(self.ctxt)
        self.volume_file.seek(0)
        service1.backup(backup, self.volume_file)

        # Create incremental backup with no change to contents
        self.volume_file.seek(2 * 8 * units.Ki)
        self.volume_file.write(os.urandom(units.Ki))
        self.volume_file.seek(4 * 8 * units.Ki)
        self.volume_file.write(os.urandom(units.Ki))

        deltabackup = self._create_backup_db_entry(volume_id=volume_id,
                                                   container=None,
                                                   parent_id=backup.id)
        service2 = s3_dr.S3BackupDriver(self.ctxt)
        self.volume_file.seek(0)
        service2.backup(deltabackup, self.volume_file)

        content1 = service1._read_sha256file(backup)
        content2 = service2._read_sha256file(deltabackup)

        # Verify that two shas are changed at index 16 and 32
        self.assertNotEqual(content1['sha256s'][16], content2['sha256s'][16])
        self.assertNotEqual(content1['sha256s'][32], content2['sha256s'][32])

    @mock_s3
    def test_backup_delta_two_blocks_in_object_change(self):
        volume_id = 'b943e84f-aa67-4331-9ab2-000000cf19ba'

        self.flags(backup_s3_object_size=8 * units.Ki)
        self.flags(backup_s3_block_size=units.Ki)

        backup = self._create_backup_db_entry(volume_id=volume_id)

        service1 = s3_dr.S3BackupDriver(self.ctxt)
        self.volume_file.seek(0)
        service1.backup(backup, self.volume_file)

        # Create incremental backup with no change to contents
        self.volume_file.seek(16 * units.Ki)
        self.volume_file.write(os.urandom(units.Ki))
        self.volume_file.seek(20 * units.Ki)
        self.volume_file.write(os.urandom(units.Ki))

        deltabackup = self._create_backup_db_entry(volume_id=volume_id,
                                                   container=None,
                                                   parent_id=backup.id)
        service2 = s3_dr.S3BackupDriver(self.ctxt)
        self.volume_file.seek(0)
        service2.backup(deltabackup, self.volume_file)

        # Verify that two shas are changed at index 16 and 20
        content1 = service1._read_sha256file(backup)
        content2 = service2._read_sha256file(deltabackup)
        self.assertNotEqual(content1['sha256s'][16], content2['sha256s'][16])
        self.assertNotEqual(content1['sha256s'][20], content2['sha256s'][20])

    @mock_s3
    @mock.patch('cinder.backup.drivers.s3.S3BackupDriver.'
                '_send_progress_end')
    @mock.patch('cinder.backup.drivers.s3.S3BackupDriver.'
                '_send_progress_notification')
    def test_backup_default_container_notify(self, _send_progress,
                                             _send_progress_end):
        volume_id = '87dd0eed-2598-4ebd-8ebb-000000ac578a'
        backup = self._create_backup_db_entry(volume_id=volume_id,
                                              container=None)
        # If the backup_object_number_per_notification is set to 1,
        # the _send_progress method will be called for sure.
        s3_dr.CONF.set_override("backup_object_number_per_notification", 1)
        s3_dr.CONF.set_override("backup_s3_enable_progress_timer", False)
        service = s3_dr.S3BackupDriver(self.ctxt)
        self.volume_file.seek(0)
        service.backup(backup, self.volume_file)
        self.assertTrue(_send_progress.called)
        self.assertTrue(_send_progress_end.called)

        # If the backup_object_number_per_notification is increased to
        # another value, the _send_progress method will not be called.
        _send_progress.reset_mock()
        _send_progress_end.reset_mock()
        s3_dr.CONF.set_override("backup_object_number_per_notification",
                                10)
        service = s3_dr.S3BackupDriver(self.ctxt)
        self.volume_file.seek(0)
        service.backup(backup, self.volume_file)
        self.assertFalse(_send_progress.called)
        self.assertTrue(_send_progress_end.called)

        # If the timer is enabled, the _send_progress will be called,
        # since the timer can trigger the progress notification.
        _send_progress.reset_mock()
        _send_progress_end.reset_mock()
        s3_dr.CONF.set_override("backup_object_number_per_notification",
                                10)
        s3_dr.CONF.set_override("backup_s3_enable_progress_timer", True)
        service = s3_dr.S3BackupDriver(self.ctxt)
        self.volume_file.seek(0)
        service.backup(backup, self.volume_file)
        self.assertTrue(_send_progress.called)
        self.assertTrue(_send_progress_end.called)

    @mock_s3
    @mock.patch.object(s3_dr.S3BackupDriver, '_backup_metadata',
                       fake_backup_metadata)
    def test_backup_backup_metadata_fail(self):
        """Test of when an exception occurs in backup().

        In backup(), after an exception occurs in
        self._backup_metadata(), we want to check the process of an
        exception handler.
        """
        volume_id = '020d9142-339c-4876-a445-000000f1520c'

        backup = self._create_backup_db_entry(volume_id=volume_id)
        self.flags(backup_compression_algorithm='none')
        service = s3_dr.S3BackupDriver(self.ctxt)
        self.volume_file.seek(0)
        # We expect that an exception be notified directly.
        self.assertRaises(exception.BackupDriverException,
                          service.backup,
                          backup, self.volume_file)

    @mock_s3
    @mock.patch.object(s3_dr.S3BackupDriver, '_backup_metadata',
                       fake_backup_metadata)
    @mock.patch.object(s3_dr.S3BackupDriver, 'delete_backup',
                       fake_delete)
    def test_backup_backup_metadata_fail2(self):
        """Test of when an exception occurs in an exception handler.

        In backup(), after an exception occurs in
        self._backup_metadata(), we want to check the process when the
        second exception occurs in self.delete_backup().
        """
        volume_id = '2164421d-f181-4db7-b9bd-000000eeb628'

        backup = self._create_backup_db_entry(volume_id=volume_id)
        self.flags(backup_compression_algorithm='none')
        service = s3_dr.S3BackupDriver(self.ctxt)
        self.volume_file.seek(0)
        # We expect that the second exception is notified.
        self.assertRaises(exception.BackupOperationError,
                          service.backup,
                          backup, self.volume_file)

    @mock_s3
    def test_delete(self):
        volume_id = '9ab256c8-3175-4ad8-baa1-0000007f9d31'
        object_prefix = 'test_prefix'
        backup = self._create_backup_db_entry(volume_id=volume_id,
                                              service_metadata=object_prefix)
        service = s3_dr.S3BackupDriver(self.ctxt)
        service.delete_backup(backup)

    @mock_s3
    @mock.patch.object(s3_dr.S3BackupDriver, 'delete_object',
                       _fake_delete_object)
    def test_delete_without_object_prefix(self):
        volume_id = 'ee30d649-72a6-49a5-b78d-000000edb6b1'
        backup = self._create_backup_db_entry(volume_id=volume_id)
        service = s3_dr.S3BackupDriver(self.ctxt)
        service.delete_backup(backup)

    @mock_s3
    def test_get_compressor(self):
        service = s3_dr.S3BackupDriver(self.ctxt)
        compressor = service._get_compressor('None')
        self.assertIsNone(compressor)
        compressor = service._get_compressor('zlib')
        self.assertEqual(zlib, compressor)
        self.assertIsInstance(compressor, tpool.Proxy)
        compressor = service._get_compressor('bz2')
        self.assertEqual(bz2, compressor)
        self.assertIsInstance(compressor, tpool.Proxy)
        self.assertRaises(ValueError, service._get_compressor, 'fake')

    @mock_s3
    def test_prepare_output_data_effective_compression(self):
        """Test compression works on a native thread."""
        # Use dictionary to share data between threads
        thread_dict = {}
        original_compress = zlib.compress

        def my_compress(data):
            thread_dict['compress'] = threading.current_thread()
            return original_compress(data)

        self.mock_object(zlib, 'compress', side_effect=my_compress)

        service = s3_dr.S3BackupDriver(self.ctxt)
        # Set up buffer of 128 zeroed bytes
        fake_data = b'\0' * 128

        result = service._prepare_output_data(fake_data)

        self.assertEqual('zlib', result[0])
        self.assertGreater(len(fake_data), len(result[1]))
        self.assertNotEqual(threading.current_thread(),
                            thread_dict['compress'])

    @mock_s3
    def test_prepare_output_data_no_compression(self):
        self.flags(backup_compression_algorithm='none')
        service = s3_dr.S3BackupDriver(self.ctxt)
        # Set up buffer of 128 zeroed bytes
        fake_data = b'\0' * 128

        result = service._prepare_output_data(fake_data)

        self.assertEqual('none', result[0])
        self.assertEqual(fake_data, result[1])

    @mock_s3
    def test_prepare_output_data_ineffective_compression(self):
        service = s3_dr.S3BackupDriver(self.ctxt)
        # Set up buffer of 128 zeroed bytes
        fake_data = b'\0' * 128
        # Pre-compress so that compression in the driver will be ineffective.
        already_compressed_data = service.compressor.compress(fake_data)

        result = service._prepare_output_data(already_compressed_data)

        self.assertEqual('none', result[0])
        self.assertEqual(already_compressed_data, result[1])

    @mock_s3
    def test_no_config_option(self):
        # With no config option to connect driver should raise exception.
        self.flags(backup_s3_endpoint_url=None)
        self.flags(backup_s3_store_access_key=None)
        self.flags(backup_s3_store_secret_key=None)
        self.assertRaises(exception.InvalidConfigurationValue,
                          s3_dr.S3BackupDriver.check_for_setup_error,
                          self)

    @s3_client
    def test_create_backup_fail(self):
        volume_id = 'b09b1ad4-5f0e-4d3f-8b9e-0000004f5ec3'
        container_name = 's3_api_failure'
        backup = self._create_backup_db_entry(volume_id=volume_id,
                                              container=container_name)
        service = s3_dr.S3BackupDriver(self.ctxt)
        self.volume_file.seek(0)
        self.assertRaises(s3_dr.S3ClientError,
                          service.backup,
                          backup, self.volume_file)

    @s3_client
    def test_create_backup_faili2(self):
        volume_id = '2a59c20e-0b79-4f57-aa63-5be208df48f6'
        container_name = 's3_connection_error'
        backup = self._create_backup_db_entry(volume_id=volume_id,
                                              container=container_name)
        service = s3_dr.S3BackupDriver(self.ctxt)
        self.volume_file.seek(0)
        self.assertRaises(s3_dr.S3ConnectionFailure,
                          service.backup,
                          backup, self.volume_file)

    @mock_s3
    def test_restore(self):
        volume_id = 'c2a81f09-f480-4325-8424-00000071685b'
        backup = self._create_backup_db_entry(
            volume_id=volume_id,
            status=objects.fields.BackupStatus.RESTORING)
        service = s3_dr.S3BackupDriver(self.ctxt)
        self.volume_file.seek(0)
        service.backup(backup, self.volume_file)

        with tempfile.NamedTemporaryFile() as volume_file:
            service.restore(backup, volume_id, volume_file)

    @mock_s3
    def test_restore_delta(self):
        volume_id = '04d83506-bcf7-4ff5-9c65-00000051bd2e'
        self.flags(backup_s3_object_size=8 * units.Ki)
        self.flags(backup_s3_block_size=units.Ki)
        backup = self._create_backup_db_entry(volume_id=volume_id)
        service1 = s3_dr.S3BackupDriver(self.ctxt)
        self.volume_file.seek(0)
        service1.backup(backup, self.volume_file)

        # Create incremental backup with no change to contents
        self.volume_file.seek(16 * units.Ki)
        self.volume_file.write(os.urandom(units.Ki))
        self.volume_file.seek(20 * units.Ki)
        self.volume_file.write(os.urandom(units.Ki))

        deltabackup = self._create_backup_db_entry(
            volume_id=volume_id,
            status=objects.fields.BackupStatus.RESTORING,
            parent_id=backup.id)
        self.volume_file.seek(0)
        service2 = s3_dr.S3BackupDriver(self.ctxt)
        service2.backup(deltabackup, self.volume_file, True)

        with tempfile.NamedTemporaryFile() as restored_file:
            service2.restore(deltabackup, volume_id,
                             restored_file)
            self.assertTrue(filecmp.cmp(self.volume_file.name,
                            restored_file.name))

    @s3_client
    def test_restore_fail(self):
        volume_id = '651496c7-0d8b-45f3-bfe8-9ef6ad30910f'
        container_name = 's3_api_failure'
        backup = self._create_backup_db_entry(volume_id=volume_id,
                                              container=container_name)
        service = s3_dr.S3BackupDriver(self.ctxt)

        with tempfile.NamedTemporaryFile() as volume_file:
            self.assertRaises(s3_dr.S3ClientError,
                              service.restore,
                              backup, volume_id, volume_file)

    @s3_client
    def test_restore_faili2(self):
        volume_id = '87f3f2c2-1a79-48c1-9d98-47c4cab7bf00'
        container_name = 's3_connection_error'
        backup = self._create_backup_db_entry(volume_id=volume_id,
                                              container=container_name)
        service = s3_dr.S3BackupDriver(self.ctxt)

        with tempfile.NamedTemporaryFile() as volume_file:
            self.assertRaises(s3_dr.S3ConnectionFailure,
                              service.restore,
                              backup, volume_id, volume_file)

    @mock_s3
    def test_backup_md5_validation(self):
        volume_id = 'c0a79eb2-ef56-4de2-b3b9-3861fcdf7fad'
        self.flags(backup_s3_md5_validation=True)
        backup = self._create_backup_db_entry(volume_id=volume_id)
        service = s3_dr.S3BackupDriver(self.ctxt)
        self.volume_file.seek(0)
        service.backup(backup, self.volume_file)

    @mock_s3
    def test_backup_sse(self):
        volume_id = 'c0a79eb2-ef56-4de2-b3b9-3861fcdf7fad'
        self.flags(backup_s3_sse_customer_algorithm='AES256')
        self.flags(backup_s3_sse_customer_key='sse_key')
        backup = self._create_backup_db_entry(volume_id=volume_id)
        service = s3_dr.S3BackupDriver(self.ctxt)
        self.volume_file.seek(0)
        service.backup(backup, self.volume_file)

    @mock_s3
    def test_restore_sse(self):
        volume_id = 'c0a79eb2-ef56-4de2-b3b9-3861fcdf7fad'
        self.flags(backup_s3_sse_customer_algorithm='AES256')
        self.flags(backup_s3_sse_customer_key='sse_key')
        backup = self._create_backup_db_entry(
            volume_id=volume_id,
            status=objects.fields.BackupStatus.RESTORING)
        service = s3_dr.S3BackupDriver(self.ctxt)
        self.volume_file.seek(0)
        service.backup(backup, self.volume_file)

        with tempfile.NamedTemporaryFile() as volume_file:
            service.restore(backup, volume_id, volume_file)
