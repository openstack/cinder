# Copyright (C) 2012 Hewlett-Packard Development Company, L.P.
# Copyright (C) 2016 Vedams Inc.
# Copyright (C) 2016 Google Inc.
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
Tests for Google Backup code.

"""

import bz2
import filecmp
import hashlib
import os
import shutil
import tempfile
import threading
import zlib

from eventlet import tpool
import mock
from oslo_utils import units

from cinder.backup.drivers import gcs as google_dr
from cinder import context
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder import test
from cinder.tests.unit.backup import fake_google_client
from cinder.tests.unit.backup import fake_google_client2
from cinder.tests.unit import fake_constants as fake


class FakeMD5(object):
    def __init__(self, *args, **kwargs):
        pass

    @classmethod
    def digest(self):
        return 'gcscindermd5'

    @classmethod
    def hexdigest(self):
        return 'gcscindermd5'


class FakeObjectName(object):
    @classmethod
    def _fake_generate_object_name_prefix(self, backup):
        az = 'az_fake'
        backup_name = '%s_backup_%s' % (az, backup.id)
        volume = 'volume_%s' % (backup.volume_id)
        prefix = volume + '_' + backup_name
        return prefix


def gcs_client(func):
    @mock.patch.object(google_dr.client, 'GoogleCredentials',
                       fake_google_client.FakeGoogleCredentials)
    @mock.patch.object(google_dr.discovery, 'build',
                       fake_google_client.FakeGoogleDiscovery.Build)
    @mock.patch.object(google_dr, 'GoogleMediaIoBaseDownload',
                       fake_google_client.FakeGoogleMediaIoBaseDownload)
    @mock.patch.object(hashlib, 'md5', FakeMD5)
    def func_wrapper(self, *args, **kwargs):
        if google_dr.service_account:
            with mock.patch.object(google_dr.service_account.Credentials,
                                   'from_service_account_file',
                                   fake_google_client.FakeGoogleCredentials):
                return func(self, *args, **kwargs)
        return func(self, *args, **kwargs)

    return func_wrapper


def gcs_client2(func):
    @mock.patch.object(google_dr.client, 'GoogleCredentials',
                       fake_google_client2.FakeGoogleCredentials)
    @mock.patch.object(google_dr.discovery, 'build',
                       fake_google_client2.FakeGoogleDiscovery.Build)
    @mock.patch.object(google_dr, 'GoogleMediaIoBaseDownload',
                       fake_google_client2.FakeGoogleMediaIoBaseDownload)
    @mock.patch.object(google_dr.GoogleBackupDriver,
                       '_generate_object_name_prefix',
                       FakeObjectName._fake_generate_object_name_prefix)
    @mock.patch.object(hashlib, 'md5', FakeMD5)
    def func_wrapper(self, *args, **kwargs):
        if google_dr.service_account:
            with mock.patch.object(google_dr.service_account.Credentials,
                                   'from_service_account_file',
                                   fake_google_client.FakeGoogleCredentials):
                return func(self, *args, **kwargs)
        return func(self, *args, **kwargs)

    return func_wrapper


def fake_backup_metadata(self, backup, object_meta):
    raise exception.BackupDriverException(reason=_('fake'))


def fake_delete(self, backup):
    raise exception.BackupOperationError()


def _fake_delete_object(self, bucket_name, object_name):
    raise AssertionError('delete_object method should not be called.')


class GoogleBackupDriverTestCase(test.TestCase):
    """Test Case for Google"""

    _DEFAULT_VOLUME_ID = 'c7eb81f4-bec6-4730-a60f-8888885874df'

    def _create_volume_db_entry(self, volume_id=_DEFAULT_VOLUME_ID):
        vol = {'id': volume_id,
               'size': 1,
               'status': 'available'}
        return db.volume_create(self.ctxt, vol)['id']

    def _create_backup_db_entry(self,
                                volume_id=_DEFAULT_VOLUME_ID,
                                container=google_dr.CONF.backup_gcs_bucket,
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
        super(GoogleBackupDriverTestCase, self).setUp()
        self.flags(backup_gcs_bucket='gcscinderbucket')
        self.flags(backup_gcs_credential_file='test-file')
        self.flags(backup_gcs_project_id='test-gcs')
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
        # Note(yikun): It mocks out the backup notifier to avoid to leak
        # notifications into other test.
        notify_patcher = mock.patch(
            'cinder.volume.utils.notify_about_backup_usage')
        notify_patcher.start()
        self.addCleanup(notify_patcher.stop)

    @gcs_client
    def test_backup(self):
        volume_id = 'b09b1ad4-5f0e-4d3f-8b9e-0000004f5ec2'
        container_name = 'test-bucket'
        backup = self._create_backup_db_entry(volume_id=volume_id,
                                              container=container_name)
        service = google_dr.GoogleBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        result = service.backup(backup, self.volume_file)
        self.assertIsNone(result)

    @gcs_client
    def test_backup_uncompressed(self):
        volume_id = '2b9f10a3-42b4-4fdf-b316-000000ceb039'
        backup = self._create_backup_db_entry(volume_id=volume_id)
        self.flags(backup_compression_algorithm='none')
        service = google_dr.GoogleBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        service.backup(backup, self.volume_file)

    @gcs_client
    def test_backup_bz2(self):
        volume_id = 'dc0fee35-b44e-4f13-80d6-000000e1b50c'
        backup = self._create_backup_db_entry(volume_id=volume_id)
        self.flags(backup_compression_algorithm='bz2')
        service = google_dr.GoogleBackupDriver(self.ctxt)
        self._write_effective_compression_file(self.size_volume_file)
        service.backup(backup, self.volume_file)

    @gcs_client
    def test_backup_zlib(self):
        volume_id = '5cea0535-b6fb-4531-9a38-000000bea094'
        backup = self._create_backup_db_entry(volume_id=volume_id)
        self.flags(backup_compression_algorithm='zlib')
        service = google_dr.GoogleBackupDriver(self.ctxt)
        self._write_effective_compression_file(self.size_volume_file)
        service.backup(backup, self.volume_file)

    @gcs_client
    def test_backup_default_container(self):
        volume_id = '9552017f-c8b9-4e4e-a876-00000053349c'
        backup = self._create_backup_db_entry(volume_id=volume_id,
                                              container=None)
        service = google_dr.GoogleBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        service.backup(backup, self.volume_file)
        self.assertEqual('gcscinderbucket', backup.container)

    @gcs_client
    @mock.patch('httplib2.proxy_info_from_url')
    def test_backup_proxy_configured(self, mock_proxy_info):
        # Configuration overwrites enviromental variable
        proxy_cfg = "http://myproxy.example.com"
        os.environ['http_proxy'] = proxy_cfg + '_fake'
        google_dr.CONF.set_override("backup_gcs_proxy_url", proxy_cfg)
        google_dr.GoogleBackupDriver(self.ctxt)
        self.assertEqual(proxy_cfg, os.environ.get('http_proxy'))

    @gcs_client
    @mock.patch('cinder.backup.drivers.gcs.GoogleBackupDriver.'
                '_send_progress_end')
    @mock.patch('cinder.backup.drivers.gcs.GoogleBackupDriver.'
                '_send_progress_notification')
    def test_backup_default_container_notify(self, _send_progress,
                                             _send_progress_end):
        volume_id = '87dd0eed-2598-4ebd-8ebb-000000ac578a'
        backup = self._create_backup_db_entry(volume_id=volume_id,
                                              container=None)
        # If the backup_object_number_per_notification is set to 1,
        # the _send_progress method will be called for sure.
        google_dr.CONF.set_override("backup_object_number_per_notification", 1)
        google_dr.CONF.set_override("backup_gcs_enable_progress_timer", False)
        service = google_dr.GoogleBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        service.backup(backup, self.volume_file)
        self.assertTrue(_send_progress.called)
        self.assertTrue(_send_progress_end.called)

        # If the backup_object_number_per_notification is increased to
        # another value, the _send_progress method will not be called.
        _send_progress.reset_mock()
        _send_progress_end.reset_mock()
        google_dr.CONF.set_override("backup_object_number_per_notification",
                                    10)
        service = google_dr.GoogleBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        service.backup(backup, self.volume_file)
        self.assertFalse(_send_progress.called)
        self.assertTrue(_send_progress_end.called)

        # If the timer is enabled, the _send_progress will be called,
        # since the timer can trigger the progress notification.
        _send_progress.reset_mock()
        _send_progress_end.reset_mock()
        google_dr.CONF.set_override("backup_object_number_per_notification",
                                    10)
        google_dr.CONF.set_override("backup_gcs_enable_progress_timer", True)
        service = google_dr.GoogleBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        service.backup(backup, self.volume_file)
        self.assertTrue(_send_progress.called)
        self.assertTrue(_send_progress_end.called)

    @gcs_client
    def test_backup_custom_container(self):
        volume_id = '1da9859e-77e5-4731-bd58-000000ca119e'
        container_name = 'fake99'
        backup = self._create_backup_db_entry(volume_id=volume_id,
                                              container=container_name)
        service = google_dr.GoogleBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        service.backup(backup, self.volume_file)
        self.assertEqual(container_name, backup.container)

    @gcs_client2
    def test_backup_shafile(self):
        volume_id = '6465dad4-22af-48f7-8a1a-000000218907'

        container_name = self.temp_dir.replace(tempfile.gettempdir() + '/',
                                               '', 1)
        backup = self._create_backup_db_entry(volume_id=volume_id,
                                              container=container_name)
        service = google_dr.GoogleBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        service.backup(backup, self.volume_file)
        self.assertEqual(container_name, backup.container)

        # Verify sha contents
        content1 = service._read_sha256file(backup)
        self.assertEqual(64 * units.Ki / content1['chunk_size'],
                         len(content1['sha256s']))

    @gcs_client2
    def test_backup_cmp_shafiles(self):
        volume_id = '1a99ac67-c534-4fe3-b472-0000001785e2'

        container_name = self.temp_dir.replace(tempfile.gettempdir() + '/',
                                               '', 1)
        backup = self._create_backup_db_entry(volume_id=volume_id,
                                              container=container_name)
        service1 = google_dr.GoogleBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        service1.backup(backup, self.volume_file)
        self.assertEqual(container_name, backup.container)

        # Create incremental backup with no change to contents
        deltabackup = self._create_backup_db_entry(volume_id=volume_id,
                                                   container=container_name,
                                                   parent_id=backup.id)
        service2 = google_dr.GoogleBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        service2.backup(deltabackup, self.volume_file)
        self.assertEqual(container_name, deltabackup.container)

        # Compare shas from both files
        content1 = service1._read_sha256file(backup)
        content2 = service2._read_sha256file(deltabackup)

        self.assertEqual(len(content1['sha256s']), len(content2['sha256s']))
        self.assertEqual(set(content1['sha256s']), set(content2['sha256s']))

    @gcs_client2
    def test_backup_delta_two_objects_change(self):
        volume_id = '30dab288-265a-4583-9abe-000000d42c67'

        self.flags(backup_gcs_object_size=8 * units.Ki)
        self.flags(backup_gcs_block_size=units.Ki)

        container_name = self.temp_dir.replace(tempfile.gettempdir() + '/',
                                               '', 1)
        backup = self._create_backup_db_entry(volume_id=volume_id,
                                              container=container_name)
        service1 = google_dr.GoogleBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        service1.backup(backup, self.volume_file)
        self.assertEqual(container_name, backup.container)

        # Create incremental backup with no change to contents
        self.volume_file.seek(2 * 8 * units.Ki)
        self.volume_file.write(os.urandom(units.Ki))
        self.volume_file.seek(4 * 8 * units.Ki)
        self.volume_file.write(os.urandom(units.Ki))

        deltabackup = self._create_backup_db_entry(volume_id=volume_id,
                                                   container=container_name,
                                                   parent_id=backup.id)
        service2 = google_dr.GoogleBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        service2.backup(deltabackup, self.volume_file)
        self.assertEqual(container_name, deltabackup.container)

        content1 = service1._read_sha256file(backup)
        content2 = service2._read_sha256file(deltabackup)

        # Verify that two shas are changed at index 16 and 32
        self.assertNotEqual(content1['sha256s'][16], content2['sha256s'][16])
        self.assertNotEqual(content1['sha256s'][32], content2['sha256s'][32])

    @gcs_client2
    def test_backup_delta_two_blocks_in_object_change(self):
        volume_id = 'b943e84f-aa67-4331-9ab2-000000cf19ba'

        self.flags(backup_gcs_object_size=8 * units.Ki)
        self.flags(backup_gcs_block_size=units.Ki)

        container_name = self.temp_dir.replace(tempfile.gettempdir() + '/',
                                               '', 1)
        backup = self._create_backup_db_entry(volume_id=volume_id,
                                              container=container_name)

        service1 = google_dr.GoogleBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        service1.backup(backup, self.volume_file)
        self.assertEqual(container_name, backup.container)

        # Create incremental backup with no change to contents
        self.volume_file.seek(16 * units.Ki)
        self.volume_file.write(os.urandom(units.Ki))
        self.volume_file.seek(20 * units.Ki)
        self.volume_file.write(os.urandom(units.Ki))

        deltabackup = self._create_backup_db_entry(volume_id=volume_id,
                                                   container=container_name,
                                                   parent_id=backup.id)
        service2 = google_dr.GoogleBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        service2.backup(deltabackup, self.volume_file)
        self.assertEqual(container_name, deltabackup.container)

        # Verify that two shas are changed at index 16 and 20
        content1 = service1._read_sha256file(backup)
        content2 = service2._read_sha256file(deltabackup)
        self.assertNotEqual(content1['sha256s'][16], content2['sha256s'][16])
        self.assertNotEqual(content1['sha256s'][20], content2['sha256s'][20])

    @gcs_client
    def test_create_backup_fail(self):
        volume_id = 'b09b1ad4-5f0e-4d3f-8b9e-0000004f5ec3'
        container_name = 'gcs_api_failure'
        backup = self._create_backup_db_entry(volume_id=volume_id,
                                              container=container_name)
        service = google_dr.GoogleBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        self.assertRaises(exception.GCSApiFailure,
                          service.backup,
                          backup, self.volume_file)

    @gcs_client
    def test_create_backup_fail2(self):
        volume_id = 'b09b1ad4-5f0e-4d3f-8b9e-0000004f5ec4'
        container_name = 'gcs_oauth2_failure'
        backup = self._create_backup_db_entry(volume_id=volume_id,
                                              container=container_name)
        service = google_dr.GoogleBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        self.assertRaises(exception.GCSOAuth2Failure,
                          service.backup,
                          backup, self.volume_file)

    @gcs_client
    @mock.patch.object(google_dr.GoogleBackupDriver, '_backup_metadata',
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
        service = google_dr.GoogleBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        # We expect that an exception be notified directly.
        self.assertRaises(exception.BackupDriverException,
                          service.backup,
                          backup, self.volume_file)

    @gcs_client
    @mock.patch.object(google_dr.GoogleBackupDriver, '_backup_metadata',
                       fake_backup_metadata)
    @mock.patch.object(google_dr.GoogleBackupDriver, 'delete_backup',
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
        service = google_dr.GoogleBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        # We expect that the second exception is notified.
        self.assertRaises(exception.BackupOperationError,
                          service.backup,
                          backup, self.volume_file)

    @gcs_client
    def test_restore(self):
        volume_id = 'c2a81f09-f480-4325-8424-00000071685b'
        backup = self._create_backup_db_entry(
            volume_id=volume_id,
            status=objects.fields.BackupStatus.RESTORING)
        service = google_dr.GoogleBackupDriver(self.ctxt)

        with tempfile.NamedTemporaryFile() as volume_file:
            service.restore(backup, volume_id, volume_file)

    @gcs_client
    def test_restore_fail(self):
        volume_id = 'c2a81f09-f480-4325-8424-00000071685b'
        container_name = 'gcs_connection_failure'
        backup = self._create_backup_db_entry(volume_id=volume_id,
                                              container=container_name)
        service = google_dr.GoogleBackupDriver(self.ctxt)

        with tempfile.NamedTemporaryFile() as volume_file:
            self.assertRaises(exception.GCSConnectionFailure,
                              service.restore,
                              backup, volume_id, volume_file)

    @gcs_client2
    def test_restore_delta(self):
        volume_id = '04d83506-bcf7-4ff5-9c65-00000051bd2e'
        self.flags(backup_gcs_object_size=8 * units.Ki)
        self.flags(backup_gcs_block_size=units.Ki)
        container_name = self.temp_dir.replace(tempfile.gettempdir() + '/',
                                               '', 1)
        backup = self._create_backup_db_entry(volume_id=volume_id,
                                              container=container_name)
        service1 = google_dr.GoogleBackupDriver(self.ctxt)
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
            container=container_name,
            parent_id=backup.id)
        self.volume_file.seek(0)
        service2 = google_dr.GoogleBackupDriver(self.ctxt)
        service2.backup(deltabackup, self.volume_file, True)

        with tempfile.NamedTemporaryFile() as restored_file:
            service2.restore(deltabackup, volume_id,
                             restored_file)
            self.assertTrue(filecmp.cmp(self.volume_file.name,
                            restored_file.name))

    @gcs_client
    def test_delete(self):
        volume_id = '9ab256c8-3175-4ad8-baa1-0000007f9d31'
        object_prefix = 'test_prefix'
        backup = self._create_backup_db_entry(volume_id=volume_id,
                                              service_metadata=object_prefix)
        service = google_dr.GoogleBackupDriver(self.ctxt)
        service.delete_backup(backup)

    @gcs_client
    @mock.patch.object(google_dr.GoogleBackupDriver, 'delete_object',
                       _fake_delete_object)
    def test_delete_without_object_prefix(self):
        volume_id = 'ee30d649-72a6-49a5-b78d-000000edb6b1'
        backup = self._create_backup_db_entry(volume_id=volume_id)
        service = google_dr.GoogleBackupDriver(self.ctxt)
        service.delete_backup(backup)

    @gcs_client
    def test_get_compressor(self):
        service = google_dr.GoogleBackupDriver(self.ctxt)
        compressor = service._get_compressor('None')
        self.assertIsNone(compressor)
        compressor = service._get_compressor('zlib')
        self.assertEqual(zlib, compressor)
        self.assertIsInstance(compressor, tpool.Proxy)
        compressor = service._get_compressor('bz2')
        self.assertEqual(bz2, compressor)
        self.assertIsInstance(compressor, tpool.Proxy)
        self.assertRaises(ValueError, service._get_compressor, 'fake')

    @gcs_client
    def test_prepare_output_data_effective_compression(self):
        """Test compression works on a native thread."""
        # Use dictionary to share data between threads
        thread_dict = {}
        original_compress = zlib.compress

        def my_compress(data):
            thread_dict['compress'] = threading.current_thread()
            return original_compress(data)

        self.mock_object(zlib, 'compress', side_effect=my_compress)

        service = google_dr.GoogleBackupDriver(self.ctxt)
        # Set up buffer of 128 zeroed bytes
        fake_data = b'\0' * 128

        result = service._prepare_output_data(fake_data)

        self.assertEqual('zlib', result[0])
        self.assertGreater(len(fake_data), len(result[1]))
        self.assertNotEqual(threading.current_thread(),
                            thread_dict['compress'])

    @gcs_client
    def test_prepare_output_data_no_compression(self):
        self.flags(backup_compression_algorithm='none')
        service = google_dr.GoogleBackupDriver(self.ctxt)
        # Set up buffer of 128 zeroed bytes
        fake_data = b'\0' * 128

        result = service._prepare_output_data(fake_data)

        self.assertEqual('none', result[0])
        self.assertEqual(fake_data, result[1])

    @gcs_client
    def test_prepare_output_data_ineffective_compression(self):
        service = google_dr.GoogleBackupDriver(self.ctxt)
        # Set up buffer of 128 zeroed bytes
        fake_data = b'\0' * 128
        # Pre-compress so that compression in the driver will be ineffective.
        already_compressed_data = service.compressor.compress(fake_data)

        result = service._prepare_output_data(already_compressed_data)

        self.assertEqual('none', result[0])
        self.assertEqual(already_compressed_data, result[1])

    @mock.patch('googleapiclient.__version__', '1.5.5')
    @mock.patch.object(google_dr.client.GoogleCredentials, 'from_stream')
    @mock.patch.object(google_dr.discovery, 'build')
    @mock.patch.object(google_dr, 'service_account')
    def test_non_google_auth_version(self, account, build, from_stream):
        # Prior to v1.6.0 Google api client doesn't support google-auth library
        google_dr.CONF.set_override('backup_gcs_credential_file',
                                    'credentials_file')

        google_dr.GoogleBackupDriver(self.ctxt)

        from_stream.assert_called_once_with('credentials_file')
        account.Credentials.from_service_account_file.assert_not_called()
        build.assert_called_once_with('storage', 'v1', cache_discovery=False,
                                      credentials=from_stream.return_value)

    @mock.patch('googleapiclient.__version__', '1.6.6')
    @mock.patch.object(google_dr.client.GoogleCredentials, 'from_stream')
    @mock.patch.object(google_dr.discovery, 'build')
    @mock.patch.object(google_dr, 'service_account', None)
    def test_no_httplib2_auth(self, build, from_stream):
        # Google api client requires google-auth-httplib2 if not present we
        # use legacy credentials
        google_dr.CONF.set_override('backup_gcs_credential_file',
                                    'credentials_file')

        google_dr.GoogleBackupDriver(self.ctxt)

        from_stream.assert_called_once_with('credentials_file')
        build.assert_called_once_with('storage', 'v1', cache_discovery=False,
                                      credentials=from_stream.return_value)

    @mock.patch('googleapiclient.__version__', '1.6.6')
    @mock.patch.object(google_dr, 'gexceptions', mock.Mock())
    @mock.patch.object(google_dr.client.GoogleCredentials, 'from_stream')
    @mock.patch.object(google_dr.discovery, 'build')
    @mock.patch.object(google_dr, 'service_account')
    def test_google_auth_used(self, account, build, from_stream):
        # Google api client requires google-auth-httplib2 if not present we
        # use legacy credentials
        google_dr.CONF.set_override('backup_gcs_credential_file',
                                    'credentials_file')

        google_dr.GoogleBackupDriver(self.ctxt)

        from_stream.assert_not_called()
        create_creds = account.Credentials.from_service_account_file
        create_creds.assert_called_once_with('credentials_file')
        build.assert_called_once_with('storage', 'v1', cache_discovery=False,
                                      credentials=create_creds.return_value)
