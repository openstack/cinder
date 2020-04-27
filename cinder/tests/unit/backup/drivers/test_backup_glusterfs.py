# Copyright (c) 2013 Red Hat, Inc.
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
"""Tests for GlusterFS backup driver."""
import os
from unittest import mock

from os_brick.remotefs import remotefs as remotefs_brick

from cinder.backup.drivers import glusterfs
from cinder import context
from cinder import exception
from cinder.tests.unit import test
from cinder import utils

FAKE_BACKUP_MOUNT_POINT_BASE = '/fake/mount-point-base'
FAKE_HOST = 'fake_host'
FAKE_VOL_NAME = 'backup_vol'
FAKE_BACKUP_SHARE = '%s:%s' % (FAKE_HOST, FAKE_VOL_NAME)
FAKE_BACKUP_PATH = os.path.join(FAKE_BACKUP_MOUNT_POINT_BASE,
                                'e51e43e3c63fd5770e90e58e2eafc709')


class BackupGlusterfsShareTestCase(test.TestCase):

    def setUp(self):
        super(BackupGlusterfsShareTestCase, self).setUp()
        self.ctxt = context.get_admin_context()

    def test_check_configuration(self):
        self.override_config('glusterfs_backup_share', FAKE_BACKUP_SHARE)
        self.mock_object(glusterfs.GlusterfsBackupDriver,
                         '_init_backup_repo_path',
                         return_value=FAKE_BACKUP_PATH)

        driver = glusterfs.GlusterfsBackupDriver(self.ctxt)
        driver.check_for_setup_error()

    def test_check_configuration_no_backup_share(self):
        self.override_config('glusterfs_backup_share', None)
        self.mock_object(glusterfs.GlusterfsBackupDriver,
                         '_init_backup_repo_path',
                         return_value=FAKE_BACKUP_PATH)

        driver = glusterfs.GlusterfsBackupDriver(self.ctxt)
        self.assertRaises(exception.InvalidConfigurationValue,
                          driver.check_for_setup_error)

    def test_init_backup_repo_path(self):
        self.override_config('glusterfs_backup_share', FAKE_BACKUP_SHARE)
        self.override_config('glusterfs_backup_mount_point',
                             FAKE_BACKUP_MOUNT_POINT_BASE)
        mock_remotefsclient = mock.Mock()
        mock_remotefsclient.get_mount_point = mock.Mock(
            return_value=FAKE_BACKUP_PATH)
        self.mock_object(glusterfs.GlusterfsBackupDriver,
                         'check_for_setup_error')
        self.mock_object(remotefs_brick, 'RemoteFsClient',
                         return_value=mock_remotefsclient)
        self.mock_object(os, 'getegid',
                         return_value=333333)
        self.mock_object(utils, 'get_file_gid',
                         return_value=333333)
        self.mock_object(utils, 'get_file_mode',
                         return_value=00000)
        self.mock_object(utils, 'get_root_helper')

        with mock.patch.object(glusterfs.GlusterfsBackupDriver,
                               '_init_backup_repo_path'):
            driver = glusterfs.GlusterfsBackupDriver(self.ctxt)
        self.mock_object(driver, '_execute')
        path = driver._init_backup_repo_path()

        self.assertEqual(FAKE_BACKUP_PATH, path)
        utils.get_root_helper.called_once()
        mock_remotefsclient.mount.assert_called_once_with(FAKE_BACKUP_SHARE)
        mock_remotefsclient.get_mount_point.assert_called_once_with(
            FAKE_BACKUP_SHARE)
