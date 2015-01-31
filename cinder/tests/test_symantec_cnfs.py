# Copyright (c) 2014 Symantec Corporation
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
from oslo_config import cfg

from cinder import context
from cinder import exception
from cinder.openstack.common import log as logging
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers import symantec_cnfs as cnfs

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class SymantecCNFSDriverTestCase(test.TestCase):

    """Test case for SymantecCNFS driver."""
    TEST_CNFS_SHARE = 'cnfs-host1:/share'
    TEST_VOL_NM = 'volume-a6707cd3-348c-45cd-9524-255be0939b60'
    TEST_SNAP_NM = 'snapshot-73368c68-1c0b-4027-ba8a-14629918945e'
    TEST_VOL_SIZE = 1
    TEST_MNT_BASE = '/cnfs/share'
    TEST_LOCAL_PATH = '/cnfs/share/mnt'
    TEST_VOL_LOCAL_PATH = TEST_LOCAL_PATH + '/' + TEST_VOL_NM
    TEST_SNAP_LOCAL_PATH = TEST_LOCAL_PATH + '/' + TEST_SNAP_NM
    TEST_SPL_SNAP_LOCAL_PATH = TEST_SNAP_LOCAL_PATH + "::snap:vxfs:"
    TEST_NFS_SHARES_CONFIG = '/etc/cinder/symc_nfs_share'
    TEST_NFS_MOUNT_OPTIONS_FAIL_NONE = ''
    TEST_NFS_MOUNT_OPTIONS_FAIL_V4 = 'nfsvers=4'
    TEST_NFS_MOUNT_OPTIONS_FAIL_V2 = 'nfsvers=2'
    TEST_NFS_MOUNT_OPTIONS_PASS_V3 = 'nfsvers=3'
    TEST_VOL_ID = 'a6707cd3-348c-45cd-9524-255be0939b60'
    SNAPSHOT_ID = '73368c68-1c0b-4027-ba8a-14629918945e'
    TEST_VOL = {'name': TEST_VOL_NM, 'size': TEST_VOL_SIZE,
                'id': TEST_VOL_ID, 'provider_location': TEST_CNFS_SHARE}
    TEST_SNAP = {'name': TEST_SNAP_NM, 'volume_name': TEST_VOL_NM,
                 'volume_id': TEST_VOL_ID, 'provider_location': None}

    def setUp(self):
        super(SymantecCNFSDriverTestCase, self).setUp()
        self.configuration = mock.Mock(conf.Configuration)
        self.configuration.nfs_shares_config = self.TEST_NFS_SHARES_CONFIG
        self.configuration.nfs_sparsed_volumes = True
        self.configuration.nfs_mount_point_base = self.TEST_MNT_BASE
        self.configuration.nfs_mount_options = (self.
                                                TEST_NFS_MOUNT_OPTIONS_PASS_V3)
        self.configuration.nfs_oversub_ratio = 1.0
        self.configuration.nfs_used_ratio = 0.95
        self.configuration.nfs_disk_util = 'df'
        self.configuration.nas_secure_file_operations = 'false'
        self.configuration.nas_secure_file_permissions = 'false'
        self.driver = cnfs.SymantecCNFSDriver(configuration=self.configuration)

    def test_throw_error_if_nfs_mount_options_not_configured(self):
        """Fail if no nfs mount options are configured"""
        drv = self.driver
        drv._mounted_shares = [self.TEST_CNFS_SHARE]
        drv._ensure_shares_mounted = mock.Mock()
        none_opts = self.TEST_NFS_MOUNT_OPTIONS_FAIL_NONE
        self.configuration.nfs_mount_options = none_opts
        self.assertRaises(
            exception.NfsException, drv.do_setup, context.RequestContext)

    def test_throw_error_if_nfs_mount_options_configured_with_NFSV2(self):
        """Fail if nfs mount options is not nfsv4 """
        drv = self.driver
        drv._mounted_shares = [self.TEST_CNFS_SHARE]
        drv._ensure_shares_mounted = mock.Mock()
        nfs_v2_opts = self.TEST_NFS_MOUNT_OPTIONS_FAIL_V2
        self.configuration.nfs_mount_options = nfs_v2_opts
        self.assertRaises(
            exception.NfsException, drv.do_setup, context.RequestContext)

    def test_throw_error_if_nfs_mount_options_configured_with_NFSV4(self):
        """Fail if nfs mount options is not nfsv4 """
        drv = self.driver
        drv._ensure_shares_mounted = mock.Mock()
        drv._mounted_shares = [self.TEST_CNFS_SHARE]
        nfs_v4_opts = self.TEST_NFS_MOUNT_OPTIONS_FAIL_V4
        self.configuration.nfs_mount_options = nfs_v4_opts
        self.assertRaises(
            exception.NfsException, drv.do_setup, context.RequestContext)

    @mock.patch.object(cnfs.SymantecCNFSDriver, '_get_local_volume_path')
    @mock.patch.object(os.path, 'exists')
    def test_do_clone_volume_success(self, m_exists, m_get_local_volume_path):
        """test _do_clone_volume() when filesnap over nfs is supported"""
        drv = self.driver
        m_get_local_volume_path(self.TEST_CNFS_SHARE, self.TEST_SNAP_NM).\
            return_value = self.TEST_SNAP_LOCAL_PATH
        m_get_local_volume_path(self.TEST_CNFS_SHARE, self.TEST_VOL_NM).\
            return_value = self.TEST_VOL_LOCAL_PATH
        with mock.patch.object(drv, '_execute'):
            m_exists.return_value = True
            drv._do_clone_volume(self.TEST_VOL, self.TEST_VOL_NM,
                                 self.TEST_SNAP)
            self.assertEqual(self.TEST_VOL['provider_location'],
                             self.TEST_SNAP['provider_location'])

    @mock.patch.object(cnfs.SymantecCNFSDriver, '_get_local_volume_path')
    @mock.patch.object(os.path, 'exists')
    def test_do_clone_volume_fail(self, m_exists, m_get_local_volume_path):
        """test _do_clone_volume() when filesnap over nfs is supported"""
        drv = self.driver
        m_get_local_volume_path(self.TEST_CNFS_SHARE, self.TEST_SNAP_NM).\
            return_value = self.TEST_SNAP_LOCAL_PATH
        m_get_local_volume_path(self.TEST_CNFS_SHARE, self.TEST_VOL_NM).\
            return_value = self.TEST_VOL_LOCAL_PATH
        with mock.patch.object(drv, '_execute'):
            m_exists.return_value = False
            self.assertRaises(exception.NfsException, drv._do_clone_volume,
                              self.TEST_VOL, self.TEST_VOL_NM,
                              self.TEST_SNAP)

    def assign_provider_loc(self, src_vol, tgt_vol):
        tgt_vol['provider_location'] = src_vol['provider_location']

    @mock.patch.object(cnfs.SymantecCNFSDriver, '_do_clone_volume')
    def test_create_volume_from_snapshot(self, m_do_clone_volume):
        """test create volume from snapshot"""
        drv = self.driver
        self.TEST_SNAP['provider_location'] = self.TEST_CNFS_SHARE
        self.TEST_VOL['provider_location'] = None
        loc = self.assign_provider_loc(self.TEST_SNAP, self.TEST_VOL)
        m_do_clone_volume(self.TEST_SNAP, self.TEST_SNAP_NM,
                          self.TEST_VOL).return_value = loc
        loc = drv.create_volume_from_snapshot(self.TEST_VOL, self.TEST_SNAP)
        self.assertIsNotNone(loc)

    @mock.patch.object(cnfs.SymantecCNFSDriver, '_volid_to_vol')
    @mock.patch.object(cnfs.SymantecCNFSDriver, '_do_clone_volume')
    def test_create_snapshot(self, m_do_clone_volume, m_volid_to_vol):
        """test create snapshot"""
        drv = self.driver
        self.TEST_SNAP['provider_location'] = None
        self.TEST_VOL['provider_location'] = self.TEST_CNFS_SHARE
        m_volid_to_vol(self.TEST_SNAP['volume_id']).AndReturn(self.TEST_VOL)
        m_do_clone_volume(self.TEST_VOL, self.TEST_VOL_NM, self.TEST_SNAP).\
            AndReturn(self.assign_provider_loc(self.TEST_VOL, self.TEST_SNAP))
        loc = drv.create_snapshot(self.TEST_SNAP)
        self.assertIsNotNone(loc)

    @mock.patch.object(cnfs.SymantecCNFSDriver, '_ensure_share_mounted')
    @mock.patch.object(cnfs.SymantecCNFSDriver, 'local_path')
    def test_delete_snapshot(self, m_local_path, m_ensure_share_mounted):
        """test delete snapshot"""
        drv = self.driver
        self.TEST_SNAP['provider_location'] = self.TEST_CNFS_SHARE
        m_ensure_share_mounted(self.TEST_CNFS_SHARE).AndReturn(None)
        m_local_path(self.TEST_SNAP).AndReturn(self.TEST_SNAP_LOCAL_PATH)
        with mock.patch.object(drv, '_execute'):
            drv.delete_snapshot(self.TEST_SNAP)
