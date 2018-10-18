# Copyright (c) 2017 Veritas Technologies LLC
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


import os

import mock

from cinder import context
from cinder import exception
from cinder import test
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.volume import configuration as conf
from cinder.volume.drivers import veritas_cnfs as cnfs


class VeritasCNFSDriverTestCase(test.TestCase):

    """Test case for VeritasCNFS driver."""
    TEST_CNFS_SHARE = 'cnfs-host1:/share'
    TEST_VOL_NM = 'volume-a6707cd3-348c-45cd-9524-255be0939b60'
    TEST_SNAP_NM = 'snapshot-73368c68-1c0b-4027-ba8a-14629918945e'
    TEST_VOL_SIZE = 1
    TEST_MNT_BASE = '/cnfs/share'
    TEST_LOCAL_PATH = '/cnfs/share/mnt'
    TEST_VOL_LOCAL_PATH = TEST_LOCAL_PATH + '/' + TEST_VOL_NM
    TEST_SNAP_LOCAL_PATH = TEST_LOCAL_PATH + '/' + TEST_SNAP_NM
    TEST_SPL_SNAP_LOCAL_PATH = TEST_SNAP_LOCAL_PATH + "::snap:vxfs:"
    TEST_NFS_SHARES_CONFIG = '/etc/cinder/access_nfs_share'
    TEST_NFS_MOUNT_OPTIONS_FAIL_NONE = ''
    TEST_NFS_MOUNT_OPTIONS_FAIL_V4 = 'nfsvers=4'
    TEST_NFS_MOUNT_OPTIONS_FAIL_V2 = 'nfsvers=2'
    TEST_NFS_MOUNT_OPTIONS_PASS_V3 = 'nfsvers=3'
    TEST_VOL_ID = 'a6707cd3-348c-45cd-9524-255be0939b60'
    SNAPSHOT_ID = '73368c68-1c0b-4027-ba8a-14629918945e'

    def setUp(self):
        super(VeritasCNFSDriverTestCase, self).setUp()
        self.configuration = mock.Mock(conf.Configuration)
        self.configuration.nfs_shares_config = self.TEST_NFS_SHARES_CONFIG
        self.configuration.nfs_sparsed_volumes = True
        self.configuration.nfs_mount_point_base = self.TEST_MNT_BASE
        self.configuration.nfs_mount_options = (self.
                                                TEST_NFS_MOUNT_OPTIONS_PASS_V3)
        self.configuration.nfs_oversub_ratio = 1.0
        self.configuration.nfs_used_ratio = 0.95
        self.configuration.nfs_disk_util = 'df'
        self.configuration.reserved_percentage = 0
        self.configuration.max_over_subscription_ratio = 20.0
        self.configuration.nas_secure_file_permissions = 'false'
        self.configuration.nas_secure_file_operations = 'false'
        self._loc = 'localhost:/share'
        self.context = context.get_admin_context()
        self.driver = cnfs.VeritasCNFSDriver(configuration=self.configuration)

    def test_throw_error_if_nfs_mount_options_not_configured(self):
        """Fail if no nfs mount options are configured"""
        drv = self.driver
        none_opts = self.TEST_NFS_MOUNT_OPTIONS_FAIL_NONE
        self.configuration.nfs_mount_options = none_opts
        self.assertRaises(
            exception.NfsException, drv.do_setup, context.RequestContext)

    def test_throw_error_if_nfs_mount_options_configured_with_NFSV2(self):
        """Fail if nfs mount options is not nfsv4 """
        drv = self.driver
        nfs_v2_opts = self.TEST_NFS_MOUNT_OPTIONS_FAIL_V2
        self.configuration.nfs_mount_options = nfs_v2_opts
        self.assertRaises(
            exception.NfsException, drv.do_setup, context.RequestContext)

    def test_throw_error_if_nfs_mount_options_configured_with_NFSV4(self):
        """Fail if nfs mount options is not nfsv4 """
        drv = self.driver
        nfs_v4_opts = self.TEST_NFS_MOUNT_OPTIONS_FAIL_V4
        self.configuration.nfs_mount_options = nfs_v4_opts
        self.assertRaises(
            exception.NfsException, drv.do_setup, context.RequestContext)

    @mock.patch.object(cnfs.VeritasCNFSDriver, '_get_local_volume_path')
    @mock.patch.object(os.path, 'exists')
    def test_do_clone_volume_success(self, m_exists, m_get_local_volume_path):
        """test _do_clone_volume() when filesnap over nfs is supported"""
        drv = self.driver
        volume = fake_volume.fake_volume_obj(self.context,
                                             provider_location=self._loc)
        snapshot = fake_volume.fake_volume_obj(self.context)
        with mock.patch('cinder.privsep.path.symlink'):
            m_exists.return_value = True
            drv._do_clone_volume(volume, volume.name, snapshot)

    @mock.patch.object(cnfs.VeritasCNFSDriver, '_get_local_volume_path')
    @mock.patch.object(os.path, 'exists')
    @mock.patch('cinder.privsep.path.symlink')
    def test_do_clone_volume_fail(
            self, m_symlink, m_exists, m_get_local_volume_path):
        """test _do_clone_volume() when filesnap over nfs is supported"""
        drv = self.driver
        volume = fake_volume.fake_volume_obj(self.context)
        snapshot = fake_volume.fake_volume_obj(self.context)
        with mock.patch.object(drv, '_execute'):
            m_exists.return_value = False
            self.assertRaises(exception.NfsException, drv._do_clone_volume,
                              volume, volume.name, snapshot)

    def assign_provider_loc(self, src_vol, tgt_vol):
        tgt_vol.provider_location = src_vol.provider_location

    @mock.patch.object(cnfs.VeritasCNFSDriver, '_do_clone_volume')
    def test_create_volume_from_snapshot(self, m_do_clone_volume):
        """test create volume from snapshot"""
        drv = self.driver
        volume = fake_volume.fake_volume_obj(self.context)
        snapshot = fake_volume.fake_volume_obj(self.context,
                                               provider_location=self._loc)
        volume.size = 10
        snapshot.volume_size = 10
        m_do_clone_volume(snapshot, snapshot.name,
                          volume).return_value = True
        drv.create_volume_from_snapshot(volume, snapshot)
        self.assertEqual(volume.provider_location, snapshot.provider_location)

    @mock.patch.object(cnfs.VeritasCNFSDriver, '_get_vol_by_id')
    @mock.patch.object(cnfs.VeritasCNFSDriver, '_do_clone_volume')
    def test_create_snapshot(self, m_do_clone_volume, m_get_vol_by_id):
        """test create snapshot"""
        drv = self.driver
        volume = fake_volume.fake_volume_obj(context.get_admin_context(),
                                             provider_location=self._loc)
        snapshot = fake_snapshot.fake_snapshot_obj(context.get_admin_context())
        snapshot.volume = volume
        m_get_vol_by_id.return_value = volume
        m_do_clone_volume(snapshot, snapshot.name,
                          volume).return_value = True
        drv.create_snapshot(snapshot)
        self.assertEqual(volume.provider_location, snapshot.provider_location)

    @mock.patch.object(cnfs.VeritasCNFSDriver, '_ensure_share_mounted')
    @mock.patch.object(cnfs.VeritasCNFSDriver, 'local_path')
    def test_delete_snapshot(self, m_local_path, m_ensure_share_mounted):
        """test delete snapshot"""
        drv = self.driver
        snapshot = fake_snapshot.fake_snapshot_obj(context.get_admin_context(),
                                                   provider_location=self._loc)
        m_ensure_share_mounted(self._loc).AndReturn(None)
        m_local_path(snapshot).AndReturn(self.TEST_SNAP_LOCAL_PATH)
        with mock.patch.object(drv, '_execute'):
            drv.delete_snapshot(snapshot)

    @mock.patch.object(cnfs.VeritasCNFSDriver, '_do_clone_volume')
    @mock.patch.object(cnfs.VeritasCNFSDriver, 'local_path')
    def test_create_volume_from_snapshot_greater_size(self, m_local_path,
                                                      m_do_clone_volume):
        """test create volume from snapshot with greater volume size"""
        drv = self.driver
        volume = fake_volume.fake_volume_obj(self.context)
        snapshot = fake_volume.fake_volume_obj(self.context,
                                               provider_location=self._loc)
        volume.size = 20
        snapshot.volume_size = 10
        m_do_clone_volume(snapshot, snapshot.name,
                          volume).return_value = True
        m_local_path(volume).AndReturn(self.TEST_VOL_LOCAL_PATH)
        with mock.patch.object(drv, '_execute'):
            drv.create_volume_from_snapshot(volume, snapshot)
        self.assertEqual(volume.provider_location, snapshot.provider_location)
