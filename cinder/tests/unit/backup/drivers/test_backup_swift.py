# Copyright (C) 2012 Hewlett-Packard Development Company, L.P.
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
Tests for Backup swift code.

"""

import bz2
import ddt
import filecmp
import hashlib
import os
import shutil
import tempfile
import threading
import zlib

from eventlet import tpool
import mock
from oslo_config import cfg
from swiftclient import client as swift

from cinder.backup.drivers import swift as swift_dr
from cinder import context
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder import test
from cinder.tests.unit.backup import fake_swift_client
from cinder.tests.unit.backup import fake_swift_client2
from cinder.tests.unit import fake_constants as fake


CONF = cfg.CONF

ANY = mock.ANY


def fake_md5(arg):
    class result(object):
        def hexdigest(self):
            return 'fake-md5-sum'

    ret = result()
    return ret


@ddt.ddt
class BackupSwiftTestCase(test.TestCase):
    """Test Case for swift."""

    _DEFAULT_VOLUME_ID = 'c7eb81f4-bec6-4730-a60f-8888885874df'

    def _create_volume_db_entry(self, volume_id=_DEFAULT_VOLUME_ID):
        vol = {'id': volume_id,
               'size': 1,
               'status': 'available'}
        return db.volume_create(self.ctxt, vol)['id']

    def _create_backup_db_entry(self,
                                volume_id=_DEFAULT_VOLUME_ID,
                                container='test-container',
                                backup_id=fake.BACKUP_ID, parent_id=None,
                                service_metadata=None):

        try:
            db.volume_get(self.ctxt, volume_id)
        except exception.NotFound:
            self._create_volume_db_entry(volume_id=volume_id)

        backup = {'id': backup_id,
                  'size': 1,
                  'container': container,
                  'volume_id': volume_id,
                  'parent_id': parent_id,
                  'user_id': fake.USER_ID,
                  'project_id': fake.PROJECT_ID,
                  'service_metadata': service_metadata,
                  }
        return db.backup_create(self.ctxt, backup)['id']

    def _write_effective_compression_file(self, data_size):
        """Ensure file contents can be effectively compressed."""
        self.volume_file.seek(0)
        self.volume_file.write(bytes([65] * data_size))
        self.volume_file.seek(0)

    def setUp(self):
        super(BackupSwiftTestCase, self).setUp()
        service_catalog = [{u'type': u'object-store', u'name': u'swift',
                            u'endpoints': [{
                                u'publicURL': u'http://example.com'}]},
                           {u'type': u'identity', u'name': u'keystone',
                            u'endpoints': [{
                                u'publicURL': u'http://example.com'}]}]
        self.ctxt = context.get_admin_context()
        self.ctxt.service_catalog = service_catalog

        self.mock_object(swift, 'Connection',
                         fake_swift_client.FakeSwiftClient.Connection)
        self.mock_object(hashlib, 'md5', fake_md5)

        self.volume_file = tempfile.NamedTemporaryFile()
        self.temp_dir = tempfile.mkdtemp()
        self.addCleanup(self.volume_file.close)
        # Remove tempdir.
        self.addCleanup(shutil.rmtree, self.temp_dir)
        self.size_volume_file = 0
        for _i in range(0, 64):
            self.volume_file.write(os.urandom(1024))
            self.size_volume_file += 1024

        notify_patcher = mock.patch(
            'cinder.volume.utils.notify_about_backup_usage')
        notify_patcher.start()
        self.addCleanup(notify_patcher.stop)

    def test_backup_swift_url(self):
        self.ctxt.service_catalog = [{u'type': u'object-store',
                                      u'name': u'swift',
                                      u'endpoints': [{
                                          u'adminURL':
                                              u'http://example.com'}]},
                                     {u'type': u'identity',
                                      u'name': u'keystone',
                                      u'endpoints': [{
                                          u'publicURL':
                                              u'http://example.com'}]}]
        self.assertRaises(exception.BackupDriverException,
                          swift_dr.SwiftBackupDriver,
                          self.ctxt)

    def test_backup_swift_auth_url(self):
        self.ctxt.service_catalog = [{u'type': u'object-store',
                                      u'name': u'swift',
                                      u'endpoints': [{
                                          u'publicURL':
                                              u'http://example.com'}]},
                                     {u'type': u'identity',
                                      u'name': u'keystone',
                                      u'endpoints': [{
                                          u'adminURL':
                                              u'http://example.com'}]}]
        self.override_config("backup_swift_auth",
                             "single_user")
        self.override_config("backup_swift_user",
                             "fake_user")
        self.assertRaises(exception.BackupDriverException,
                          swift_dr.SwiftBackupDriver,
                          self.ctxt)

    def test_backup_swift_url_conf(self):
        self.ctxt.service_catalog = [{u'type': u'object-store',
                                      u'name': u'swift',
                                      u'endpoints': [{
                                          u'adminURL':
                                              u'http://example.com'}]},
                                     {u'type': u'identity',
                                     u'name': u'keystone',
                                      u'endpoints': [{
                                          u'publicURL':
                                              u'http://example.com'}]}]
        self.ctxt.project_id = fake.PROJECT_ID
        self.override_config("backup_swift_url",
                             "http://public.example.com/")
        backup = swift_dr.SwiftBackupDriver(self.ctxt)
        self.assertEqual("%s%s" % (CONF.backup_swift_url,
                                   self.ctxt.project_id),
                         backup.swift_url)

    def test_backup_swift_url_conf_nocatalog(self):
        self.ctxt.service_catalog = []
        self.ctxt.project_id = fake.PROJECT_ID
        self.override_config("backup_swift_url",
                             "http://public.example.com/")
        backup = swift_dr.SwiftBackupDriver(self.ctxt)
        self.assertEqual("%s%s" % (CONF.backup_swift_url,
                                   self.ctxt.project_id),
                         backup.swift_url)

    def test_backup_swift_auth_url_conf(self):
        self.ctxt.service_catalog = [{u'type': u'object-store',
                                      u'name': u'swift',
                                      u'endpoints': [{
                                          u'publicURL':
                                              u'http://example.com'}]},
                                     {u'type': u'identity',
                                      u'name': u'keystone',
                                      u'endpoints': [{
                                          u'adminURL':
                                              u'http://example.com'}]}]

        self.ctxt.project_id = fake.PROJECT_ID
        self.override_config("backup_swift_auth_url",
                             "http://public.example.com")
        self.override_config("backup_swift_auth",
                             "single_user")
        self.override_config("backup_swift_user",
                             "fake_user")
        backup = swift_dr.SwiftBackupDriver(self.ctxt)
        self.assertEqual(CONF.backup_swift_auth_url, backup.auth_url)

    def test_backup_swift_info(self):
        self.override_config("swift_catalog_info", "dummy")
        self.assertRaises(exception.BackupDriverException,
                          swift_dr.SwiftBackupDriver,
                          self.ctxt)

    @ddt.data(
        {'auth': 'single_user', 'insecure': True},
        {'auth': 'single_user', 'insecure': False},
        {'auth': 'per_user', 'insecure': True},
        {'auth': 'per_user', 'insecure': False},
    )
    @ddt.unpack
    def test_backup_swift_auth_insecure(self, auth, insecure):
        self.override_config("backup_swift_auth_insecure", insecure)
        self.override_config('backup_swift_auth', auth)
        if auth == 'single_user':
            self.override_config('backup_swift_user', 'swift-user')

        mock_connection = self.mock_object(swift, 'Connection')

        swift_dr.SwiftBackupDriver(self.ctxt)

        if auth == 'single_user':
            mock_connection.assert_called_once_with(insecure=insecure,
                                                    authurl=ANY,
                                                    auth_version=ANY,
                                                    tenant_name=ANY,
                                                    user=ANY,
                                                    key=ANY,
                                                    os_options={},
                                                    retries=ANY,
                                                    starting_backoff=ANY,
                                                    cacert=ANY)
        else:
            mock_connection.assert_called_once_with(insecure=insecure,
                                                    retries=ANY,
                                                    preauthurl=ANY,
                                                    preauthtoken=ANY,
                                                    starting_backoff=ANY,
                                                    cacert=ANY)

    @ddt.data(
        {'auth_version': '3', 'user_domain': 'UserDomain',
            'project': 'Project', 'project_domain': 'ProjectDomain'},
        {'auth_version': '3', 'user_domain': None,
            'project': 'Project', 'project_domain': 'ProjectDomain'},
        {'auth_version': '3', 'user_domain': 'UserDomain',
            'project': None, 'project_domain': 'ProjectDomain'},
        {'auth_version': '3', 'user_domain': 'UserDomain',
            'project': 'Project', 'project_domain': None},
        {'auth_version': '3', 'user_domain': None,
            'project': None, 'project_domain': None},
    )
    @ddt.unpack
    def test_backup_swift_auth_v3_single_user(self, auth_version, user_domain,
                                              project, project_domain):
        self.override_config('backup_swift_auth', 'single_user')
        self.override_config('backup_swift_user', 'swift-user')
        self.override_config('backup_swift_auth_version', auth_version)
        self.override_config('backup_swift_user_domain', user_domain)
        self.override_config('backup_swift_project', project)
        self.override_config('backup_swift_project_domain', project_domain)

        os_options = {}
        if user_domain is not None:
            os_options['user_domain_name'] = user_domain
        if project is not None:
            os_options['project_name'] = project
        if project_domain is not None:
            os_options['project_domain_name'] = project_domain

        mock_connection = self.mock_object(swift, 'Connection')
        swift_dr.SwiftBackupDriver(self.ctxt)
        mock_connection.assert_called_once_with(insecure=ANY,
                                                authurl=ANY,
                                                auth_version=auth_version,
                                                tenant_name=ANY,
                                                user=ANY,
                                                key=ANY,
                                                os_options=os_options,
                                                retries=ANY,
                                                starting_backoff=ANY,
                                                cacert=ANY)

    def test_backup_uncompressed(self):
        volume_id = '2b9f10a3-42b4-4fdf-b316-000000ceb039'
        self._create_backup_db_entry(volume_id=volume_id)
        self.flags(backup_compression_algorithm='none')
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP_ID)
        service.backup(backup, self.volume_file)

    def test_backup_bz2(self):
        volume_id = 'dc0fee35-b44e-4f13-80d6-000000e1b50c'
        self._create_backup_db_entry(volume_id=volume_id)
        self.flags(backup_compression_algorithm='bz2')
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        self._write_effective_compression_file(self.size_volume_file)
        backup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP_ID)
        service.backup(backup, self.volume_file)

    def test_backup_zlib(self):
        volume_id = '5cea0535-b6fb-4531-9a38-000000bea094'
        self._create_backup_db_entry(volume_id=volume_id)
        self.flags(backup_compression_algorithm='zlib')
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        self._write_effective_compression_file(self.size_volume_file)
        backup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP_ID)
        service.backup(backup, self.volume_file)

    @mock.patch.object(db, 'backup_update', wraps=db.backup_update)
    def test_backup_default_container(self, backup_update_mock):
        volume_id = '9552017f-c8b9-4e4e-a876-00000053349c'
        self._create_backup_db_entry(volume_id=volume_id,
                                     container=None)
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP_ID)
        service.backup(backup, self.volume_file)
        backup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP_ID)
        self.assertEqual('volumebackups', backup['container'])
        self.assertEqual(3, backup_update_mock.call_count)

    @mock.patch.object(db, 'backup_update', wraps=db.backup_update)
    def test_backup_db_container(self, backup_update_mock):
        volume_id = '9552017f-c8b9-4e4e-a876-00000053349c'
        self._create_backup_db_entry(volume_id=volume_id,
                                     container='existing_name')
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP_ID)

        service.backup(backup, self.volume_file)
        backup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP_ID)
        self.assertEqual('existing_name', backup['container'])
        # Make sure we are not making a DB update when we are using the same
        # value that's already in the DB.
        self.assertEqual(2, backup_update_mock.call_count)

    @mock.patch.object(db, 'backup_update', wraps=db.backup_update)
    def test_backup_driver_container(self, backup_update_mock):
        volume_id = '9552017f-c8b9-4e4e-a876-00000053349c'
        self._create_backup_db_entry(volume_id=volume_id,
                                     container=None)
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP_ID)
        with mock.patch.object(service, 'update_container_name',
                               return_value='driver_name'):
            service.backup(backup, self.volume_file)
        backup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP_ID)
        self.assertEqual('driver_name', backup['container'])
        self.assertEqual(3, backup_update_mock.call_count)

    @mock.patch('cinder.backup.drivers.swift.SwiftBackupDriver.'
                '_send_progress_end')
    @mock.patch('cinder.backup.drivers.swift.SwiftBackupDriver.'
                '_send_progress_notification')
    def test_backup_default_container_notify(self, _send_progress,
                                             _send_progress_end):
        volume_id = '87dd0eed-2598-4ebd-8ebb-000000ac578a'
        self._create_backup_db_entry(volume_id=volume_id,
                                     container=None)
        # If the backup_object_number_per_notification is set to 1,
        # the _send_progress method will be called for sure.
        CONF.set_override("backup_object_number_per_notification", 1)
        CONF.set_override("backup_swift_enable_progress_timer", False)
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP_ID)
        service.backup(backup, self.volume_file)
        self.assertTrue(_send_progress.called)
        self.assertTrue(_send_progress_end.called)

        # If the backup_object_number_per_notification is increased to
        # another value, the _send_progress method will not be called.
        _send_progress.reset_mock()
        _send_progress_end.reset_mock()
        CONF.set_override("backup_object_number_per_notification", 10)
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP_ID)
        service.backup(backup, self.volume_file)
        self.assertFalse(_send_progress.called)
        self.assertTrue(_send_progress_end.called)

        # If the timer is enabled, the _send_progress will be called,
        # since the timer can trigger the progress notification.
        _send_progress.reset_mock()
        _send_progress_end.reset_mock()
        CONF.set_override("backup_object_number_per_notification", 10)
        CONF.set_override("backup_swift_enable_progress_timer", True)
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP_ID)
        service.backup(backup, self.volume_file)
        self.assertTrue(_send_progress.called)
        self.assertTrue(_send_progress_end.called)

    def test_backup_custom_container(self):
        volume_id = '1da9859e-77e5-4731-bd58-000000ca119e'
        container_name = 'fake99'
        self._create_backup_db_entry(volume_id=volume_id,
                                     container=container_name)
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP_ID)
        service.backup(backup, self.volume_file)
        backup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP_ID)
        self.assertEqual(container_name, backup['container'])

    def test_backup_shafile(self):
        volume_id = '6465dad4-22af-48f7-8a1a-000000218907'

        def _fake_generate_object_name_prefix(self, backup):
            az = 'az_fake'
            backup_name = '%s_backup_%s' % (az, backup['id'])
            volume = 'volume_%s' % (backup['volume_id'])
            prefix = volume + '_' + backup_name
            return prefix

        self.mock_object(swift_dr.SwiftBackupDriver,
                         '_generate_object_name_prefix',
                         _fake_generate_object_name_prefix)

        container_name = self.temp_dir.replace(tempfile.gettempdir() + '/',
                                               '', 1)
        self._create_backup_db_entry(volume_id=volume_id,
                                     container=container_name)
        self.mock_object(swift, 'Connection',
                         fake_swift_client2.FakeSwiftClient2.Connection)
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP_ID)
        service.backup(backup, self.volume_file)
        backup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP_ID)
        self.assertEqual(container_name, backup['container'])

        # Verify sha contents
        content1 = service._read_sha256file(backup)
        self.assertEqual(64 * 1024 / content1['chunk_size'],
                         len(content1['sha256s']))

    def test_backup_cmp_shafiles(self):
        volume_id = '1a99ac67-c534-4fe3-b472-0000001785e2'

        def _fake_generate_object_name_prefix(self, backup):
            az = 'az_fake'
            backup_name = '%s_backup_%s' % (az, backup['id'])
            volume = 'volume_%s' % (backup['volume_id'])
            prefix = volume + '_' + backup_name
            return prefix

        self.mock_object(swift_dr.SwiftBackupDriver,
                         '_generate_object_name_prefix',
                         _fake_generate_object_name_prefix)

        container_name = self.temp_dir.replace(tempfile.gettempdir() + '/',
                                               '', 1)
        self._create_backup_db_entry(volume_id=volume_id,
                                     container=container_name,
                                     backup_id=fake.BACKUP_ID)
        self.mock_object(swift, 'Connection',
                         fake_swift_client2.FakeSwiftClient2.Connection)
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP_ID)
        service.backup(backup, self.volume_file)
        backup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP_ID)
        self.assertEqual(container_name, backup['container'])

        # Create incremental backup with no change to contents
        self._create_backup_db_entry(volume_id=volume_id,
                                     container=container_name,
                                     backup_id=fake.BACKUP2_ID,
                                     parent_id=fake.BACKUP_ID)
        self.mock_object(swift, 'Connection',
                         fake_swift_client2.FakeSwiftClient2.Connection)
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        deltabackup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP2_ID)
        service.backup(deltabackup, self.volume_file)
        deltabackup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP2_ID)
        self.assertEqual(container_name, deltabackup['container'])

        # Compare shas from both files
        content1 = service._read_sha256file(backup)
        content2 = service._read_sha256file(deltabackup)

        self.assertEqual(len(content1['sha256s']), len(content2['sha256s']))
        self.assertEqual(set(content1['sha256s']), set(content2['sha256s']))

    def test_backup_delta_two_objects_change(self):
        volume_id = '30dab288-265a-4583-9abe-000000d42c67'

        def _fake_generate_object_name_prefix(self, backup):
            az = 'az_fake'
            backup_name = '%s_backup_%s' % (az, backup['id'])
            volume = 'volume_%s' % (backup['volume_id'])
            prefix = volume + '_' + backup_name
            return prefix

        self.mock_object(swift_dr.SwiftBackupDriver,
                         '_generate_object_name_prefix',
                         _fake_generate_object_name_prefix)

        self.flags(backup_swift_object_size=8 * 1024)
        self.flags(backup_swift_block_size=1024)

        container_name = self.temp_dir.replace(tempfile.gettempdir() + '/',
                                               '', 1)
        self._create_backup_db_entry(volume_id=volume_id,
                                     container=container_name,
                                     backup_id=fake.BACKUP_ID)
        self.mock_object(swift, 'Connection',
                         fake_swift_client2.FakeSwiftClient2.Connection)
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP_ID)
        service.backup(backup, self.volume_file)
        backup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP_ID)
        self.assertEqual(container_name, backup['container'])

        # Create incremental backup with no change to contents
        self.volume_file.seek(2 * 8 * 1024)
        self.volume_file.write(os.urandom(1024))
        self.volume_file.seek(4 * 8 * 1024)
        self.volume_file.write(os.urandom(1024))

        self._create_backup_db_entry(volume_id=volume_id,
                                     container=container_name,
                                     backup_id=fake.BACKUP2_ID,
                                     parent_id=fake.BACKUP_ID)
        self.mock_object(swift, 'Connection',
                         fake_swift_client2.FakeSwiftClient2.Connection)
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        deltabackup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP2_ID)
        service.backup(deltabackup, self.volume_file)
        deltabackup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP2_ID)
        self.assertEqual(container_name, deltabackup['container'])

        content1 = service._read_sha256file(backup)
        content2 = service._read_sha256file(deltabackup)

        # Verify that two shas are changed at index 16 and 32
        self.assertNotEqual(content1['sha256s'][16], content2['sha256s'][16])
        self.assertNotEqual(content1['sha256s'][32], content2['sha256s'][32])

    def test_backup_delta_two_blocks_in_object_change(self):
        volume_id = 'b943e84f-aa67-4331-9ab2-000000cf19ba'

        def _fake_generate_object_name_prefix(self, backup):
            az = 'az_fake'
            backup_name = '%s_backup_%s' % (az, backup['id'])
            volume = 'volume_%s' % (backup['volume_id'])
            prefix = volume + '_' + backup_name
            return prefix

        self.mock_object(swift_dr.SwiftBackupDriver,
                         '_generate_object_name_prefix',
                         _fake_generate_object_name_prefix)

        self.flags(backup_swift_object_size=8 * 1024)
        self.flags(backup_swift_block_size=1024)

        container_name = self.temp_dir.replace(tempfile.gettempdir() + '/',
                                               '', 1)
        self._create_backup_db_entry(volume_id=volume_id,
                                     container=container_name,
                                     backup_id=fake.BACKUP_ID)
        self.mock_object(swift, 'Connection',
                         fake_swift_client2.FakeSwiftClient2.Connection)
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP_ID)
        service.backup(backup, self.volume_file)
        backup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP_ID)
        self.assertEqual(container_name, backup['container'])

        # Create incremental backup with no change to contents
        self.volume_file.seek(16 * 1024)
        self.volume_file.write(os.urandom(1024))
        self.volume_file.seek(20 * 1024)
        self.volume_file.write(os.urandom(1024))

        self._create_backup_db_entry(volume_id=volume_id,
                                     container=container_name,
                                     backup_id=fake.BACKUP2_ID,
                                     parent_id=fake.BACKUP_ID)
        self.mock_object(swift, 'Connection',
                         fake_swift_client2.FakeSwiftClient2.Connection)
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        deltabackup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP2_ID)
        service.backup(deltabackup, self.volume_file)
        deltabackup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP2_ID)
        self.assertEqual(container_name, deltabackup['container'])

        # Verify that two shas are changed at index 16 and 20
        content1 = service._read_sha256file(backup)
        content2 = service._read_sha256file(deltabackup)
        self.assertNotEqual(content1['sha256s'][16], content2['sha256s'][16])
        self.assertNotEqual(content1['sha256s'][20], content2['sha256s'][20])

    def test_create_backup_put_object_wraps_socket_error(self):
        volume_id = 'c09b1ad4-5f0e-4d3f-8b9e-0000004caec8'
        container_name = 'socket_error_on_put'
        self._create_backup_db_entry(volume_id=volume_id,
                                     container=container_name)
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP_ID)
        self.assertRaises(exception.SwiftConnectionFailed,
                          service.backup,
                          backup, self.volume_file)

    def test_backup_backup_metadata_fail(self):
        """Test of when an exception occurs in backup().

        In backup(), after an exception occurs in
        self._backup_metadata(), we want to check the process of an
        exception handler.
        """
        volume_id = '020d9142-339c-4876-a445-000000f1520c'

        self._create_backup_db_entry(volume_id=volume_id)
        self.flags(backup_compression_algorithm='none')
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP_ID)

        def fake_backup_metadata(self, backup, object_meta):
            raise exception.BackupDriverException(message=_('fake'))

        # Raise a pseudo exception.BackupDriverException.
        self.mock_object(swift_dr.SwiftBackupDriver, '_backup_metadata',
                         fake_backup_metadata)

        # We expect that an exception be notified directly.
        self.assertRaises(exception.BackupDriverException,
                          service.backup,
                          backup, self.volume_file)

    def test_backup_backup_metadata_fail2(self):
        """Test of when an exception occurs in an exception handler.

        In backup(), after an exception occurs in
        self._backup_metadata(), we want to check the process when the
        second exception occurs in self.delete_backup().
        """
        volume_id = '2164421d-f181-4db7-b9bd-000000eeb628'

        self._create_backup_db_entry(volume_id=volume_id)
        self.flags(backup_compression_algorithm='none')
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP_ID)

        def fake_backup_metadata(self, backup, object_meta):
            raise exception.BackupDriverException(message=_('fake'))

        # Raise a pseudo exception.BackupDriverException.
        self.mock_object(swift_dr.SwiftBackupDriver, '_backup_metadata',
                         fake_backup_metadata)

        def fake_delete(self, backup):
            raise exception.BackupOperationError()

        # Raise a pseudo exception.BackupOperationError.
        self.mock_object(swift_dr.SwiftBackupDriver, 'delete_backup',
                         fake_delete)

        # We expect that the second exception is notified.
        self.assertRaises(exception.BackupOperationError,
                          service.backup,
                          backup, self.volume_file)

    def test_restore(self):
        volume_id = 'c2a81f09-f480-4325-8424-00000071685b'
        self._create_backup_db_entry(volume_id=volume_id)
        service = swift_dr.SwiftBackupDriver(self.ctxt)

        with tempfile.NamedTemporaryFile() as volume_file:
            backup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP_ID)
            service.restore(backup, volume_id, volume_file)

    def test_restore_delta(self):
        volume_id = '04d83506-bcf7-4ff5-9c65-00000051bd2e'

        def _fake_generate_object_name_prefix(self, backup):
            az = 'az_fake'
            backup_name = '%s_backup_%s' % (az, backup['id'])
            volume = 'volume_%s' % (backup['volume_id'])
            prefix = volume + '_' + backup_name
            return prefix

        self.mock_object(swift_dr.SwiftBackupDriver,
                         '_generate_object_name_prefix',
                         _fake_generate_object_name_prefix)

        self.flags(backup_swift_object_size=8 * 1024)
        self.flags(backup_swift_block_size=1024)

        container_name = self.temp_dir.replace(tempfile.gettempdir() + '/',
                                               '', 1)
        self._create_backup_db_entry(volume_id=volume_id,
                                     container=container_name,
                                     backup_id=fake.BACKUP_ID)
        self.mock_object(swift, 'Connection',
                         fake_swift_client2.FakeSwiftClient2.Connection)
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP_ID)
        service.backup(backup, self.volume_file)

        # Create incremental backup with no change to contents
        self.volume_file.seek(16 * 1024)
        self.volume_file.write(os.urandom(1024))
        self.volume_file.seek(20 * 1024)
        self.volume_file.write(os.urandom(1024))

        self._create_backup_db_entry(volume_id=volume_id,
                                     container=container_name,
                                     backup_id=fake.BACKUP2_ID,
                                     parent_id=fake.BACKUP_ID)
        self.volume_file.seek(0)
        deltabackup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP2_ID)
        service.backup(deltabackup, self.volume_file, True)
        deltabackup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP2_ID)

        with tempfile.NamedTemporaryFile() as restored_file:
            backup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP2_ID)
            service.restore(backup, volume_id,
                            restored_file)
            self.assertTrue(filecmp.cmp(self.volume_file.name,
                            restored_file.name))

    def test_restore_wraps_socket_error(self):
        volume_id = 'c1160de7-2774-4f20-bf14-0000001ac139'
        container_name = 'socket_error_on_get'
        self._create_backup_db_entry(volume_id=volume_id,
                                     container=container_name)
        service = swift_dr.SwiftBackupDriver(self.ctxt)

        with tempfile.NamedTemporaryFile() as volume_file:
            backup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP_ID)
            self.assertRaises(exception.SwiftConnectionFailed,
                              service.restore,
                              backup, volume_id, volume_file)

    def test_restore_unsupported_version(self):
        volume_id = '390db8c1-32d3-42ca-82c9-00000010c703'
        container_name = 'unsupported_version'
        self._create_backup_db_entry(volume_id=volume_id,
                                     container=container_name)
        service = swift_dr.SwiftBackupDriver(self.ctxt)

        with tempfile.NamedTemporaryFile() as volume_file:
            backup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP_ID)
            self.assertRaises(exception.InvalidBackup,
                              service.restore,
                              backup, volume_id, volume_file)

    def test_delete(self):
        volume_id = '9ab256c8-3175-4ad8-baa1-0000007f9d31'
        object_prefix = 'test_prefix'
        self._create_backup_db_entry(volume_id=volume_id,
                                     service_metadata=object_prefix)
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        backup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP_ID)
        service.delete_backup(backup)

    def test_delete_wraps_socket_error(self):
        volume_id = 'f74cb6fa-2900-40df-87ac-0000000f72ea'
        container_name = 'socket_error_on_delete'
        object_prefix = 'test_prefix'
        self._create_backup_db_entry(volume_id=volume_id,
                                     container=container_name,
                                     service_metadata=object_prefix)
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        backup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP_ID)
        self.assertRaises(exception.SwiftConnectionFailed,
                          service.delete_backup,
                          backup)

    def test_delete_without_object_prefix(self):
        volume_id = 'ee30d649-72a6-49a5-b78d-000000edb6b1'

        def _fake_delete_object(self, container, object_name):
            raise AssertionError('delete_object method should not be called.')

        self.mock_object(swift_dr.SwiftBackupDriver,
                         'delete_object',
                         _fake_delete_object)

        self._create_backup_db_entry(volume_id=volume_id)
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        backup = objects.Backup.get_by_id(self.ctxt, fake.BACKUP_ID)
        service.delete_backup(backup)

    def test_get_compressor(self):
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        compressor = service._get_compressor('None')
        self.assertIsNone(compressor)
        compressor = service._get_compressor('zlib')
        self.assertEqual(zlib, compressor)
        self.assertIsInstance(compressor, tpool.Proxy)
        compressor = service._get_compressor('bz2')
        self.assertEqual(bz2, compressor)
        self.assertIsInstance(compressor, tpool.Proxy)
        self.assertRaises(ValueError, service._get_compressor, 'fake')

    def test_prepare_output_data_effective_compression(self):
        """Test compression works on a native thread."""
        # Use dictionary to share data between threads
        thread_dict = {}
        original_compress = zlib.compress

        def my_compress(data):
            thread_dict['compress'] = threading.current_thread()
            return original_compress(data)

        self.mock_object(zlib, 'compress', side_effect=my_compress)

        service = swift_dr.SwiftBackupDriver(self.ctxt)
        # Set up buffer of 128 zeroed bytes
        fake_data = b'\0' * 128

        result = service._prepare_output_data(fake_data)

        self.assertEqual('zlib', result[0])
        self.assertGreater(len(fake_data), len(result[1]))
        self.assertNotEqual(threading.current_thread(),
                            thread_dict['compress'])

    def test_prepare_output_data_no_compresssion(self):
        self.flags(backup_compression_algorithm='none')
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        # Set up buffer of 128 zeroed bytes
        fake_data = b'\0' * 128

        result = service._prepare_output_data(fake_data)

        self.assertEqual('none', result[0])
        self.assertEqual(fake_data, result[1])

    def test_prepare_output_data_ineffective_compression(self):
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        # Set up buffer of 128 zeroed bytes
        fake_data = b'\0' * 128
        # Pre-compress so that compression in the driver will be ineffective.
        already_compressed_data = service.compressor.compress(fake_data)

        result = service._prepare_output_data(already_compressed_data)

        self.assertEqual('none', result[0])
        self.assertEqual(already_compressed_data, result[1])
