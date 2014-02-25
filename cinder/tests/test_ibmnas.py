# Copyright 2013 IBM Corp.
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
#
# Authors:
#    Nilesh Bhosale <nilesh.bhosale@in.ibm.com>
#    Sasikanth Eda <sasikanth.eda@in.ibm.com>

"""
Tests for the IBM NAS family (SONAS, Storwize V7000 Unified).
"""

import mock

from oslo.config import cfg

from cinder import context
from cinder import exception
from cinder.openstack.common import log as logging
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.ibm import ibmnas

LOG = logging.getLogger(__name__)

CONF = cfg.CONF


class FakeEnv(object):
    fields = {}

    def __setitem__(self, key, value):
        self.fields[key] = value

    def __getitem__(self, item):
        return self.fields[item]


class IBMNASDriverTestCase(test.TestCase):

    TEST_NFS_EXPORT = 'nfs-host1:/export'
    TEST_SIZE_IN_GB = 1
    TEST_EXTEND_SIZE_IN_GB = 2
    TEST_MNT_POINT = '/mnt/nfs'
    TEST_MNT_POINT_BASE = '/mnt'
    TEST_LOCAL_PATH = '/mnt/nfs/volume-123'
    TEST_VOLUME_PATH = '/export/volume-123'
    TEST_SNAP_PATH = '/export/snapshot-123'

    def setUp(self):
        super(IBMNASDriverTestCase, self).setUp()
        self._driver = ibmnas.IBMNAS_NFSDriver(configuration=
                                               conf.Configuration(None))
        self._mock = mock.Mock()
        self._def_flags = {'nas_ip': 'hostname',
                           'nas_login': 'user',
                           'nas_ssh_port': 22,
                           'nas_password': 'pass',
                           'nas_private_key': 'nas.key',
                           'nfs_shares_config': None,
                           'nfs_sparsed_volumes': True,
                           'nfs_used_ratio': 0.95,
                           'nfs_oversub_ratio': 1.0,
                           'nfs_mount_point_base':
                           self.TEST_MNT_POINT_BASE,
                           'nfs_mount_options': None}

        self.context = context.get_admin_context()
        self.context.user_id = 'fake'
        self.context.project_id = 'fake'

    def tearDown(self):
        super(IBMNASDriverTestCase, self).tearDown()

    def _set_flag(self, flag, value):
        group = self._driver.configuration.config_group
        self._driver.configuration.set_override(flag, value, group)

    def _reset_flags(self):
        self._driver.configuration.local_conf.reset()
        for k, v in self._def_flags.iteritems():
            self._set_flag(k, v)

    def test_check_for_setup_error(self):
        """Check setup with bad parameters."""

        drv = self._driver

        required_flags = [
            'nas_ip',
            'nas_login',
            'nas_ssh_port']

        for flag in required_flags:
            self._set_flag(flag, None)
            self.assertRaises(exception.CinderException,
                              drv.check_for_setup_error)

        self._set_flag('nas_password', None)
        self._set_flag('nas_private_key', None)
        self.assertRaises(exception.InvalidInput,
                          self._driver.check_for_setup_error)

        self._reset_flags()

    def test_get_provider_location(self):
        """Check provider location for given volume id."""

        mock = self._mock

        volume = FakeEnv()
        volume['id'] = '123'

        mock.drv._get_provider_location.return_value = self.TEST_NFS_EXPORT
        self.assertEqual(self.TEST_NFS_EXPORT,
                         mock.drv._get_provider_location(volume['id']))

    def test_get_export_path(self):
        """Check export path for the given volume."""

        mock = self._mock

        volume = FakeEnv()
        volume['id'] = '123'

        mock.drv._get_export_path.return_value = self.TEST_NFS_EXPORT.\
            split(':')[1]
        self.assertEqual(self.TEST_NFS_EXPORT.split(':')[1],
                         mock.drv._get_export_path(volume['id']))

    def test_create_ibmnas_snap_mount_point_provided(self):
        """Create ibmnas snap if mount point is provided."""

        drv = self._driver
        mock = self._mock

        drv._create_ibmnas_snap = mock.drv._run_ssh.return_value.\
            drv._execute.return_value.drv._create_ibmnas_snap
        drv._create_ibmnas_snap.return_value = True
        self.assertEqual(True, mock.drv._run_ssh().
                         drv._execute().
                         drv._create_ibmnas_snap(self.TEST_VOLUME_PATH,
                                                 self.TEST_SNAP_PATH,
                                                 self.TEST_MNT_POINT))

    def test_create_ibmnas_snap_no_mount_point_provided(self):
        """Create ibmnas snap if no mount point is provided."""

        drv = self._driver
        mock = self._mock

        drv._create_ibmnas_snap = mock.drv._run_ssh.return_value.\
            drv._execute.return_value.drv._create_ibmnas_snap
        drv._create_ibmnas_snap.return_value = None
        self.assertIsNone(mock.drv._run_ssh().
                          drv._execute().
                          drv._create_ibmnas_snap(self.TEST_VOLUME_PATH,
                                                  self.TEST_SNAP_PATH,
                                                  None))

    def test_create_ibmnas_copy(self):
        """Create ibmnas copy test case."""

        drv = self._driver
        mock = self._mock

        TEST_DEST_SNAP = '/export/snapshot-123.snap'
        TEST_DEST_PATH = '/export/snapshot-123'

        drv._create_ibmnas_copy = mock.drv._run_ssh.return_value.\
            drv._create_ibmnas_copy
        drv._create_ibmnas_copy.return_value = None
        self.assertIsNone(mock.drv._run_ssh().
                          drv._create_ibmnas_copy(
                              self.TEST_VOLUME_PATH,
                              TEST_DEST_PATH,
                              TEST_DEST_SNAP))

    def test_resize_volume_file(self):
        """Resize volume file test case."""

        drv = self._driver
        mock = self._mock

        drv._resize_volume_file = mock.image_utils.resize_image.return_value.\
            drv._resize_volume_file
        drv._resize_volume_file.return_value = True
        self.assertEqual(True, mock.image_utils.resize_image().
                         drv._resize_volume_file(
                             self.TEST_LOCAL_PATH,
                             self.TEST_EXTEND_SIZE_IN_GB))

    def test_extend_volume(self):
        """Extend volume to greater size test case."""

        drv = self._driver
        mock = self._mock

        drv.extend_volume = mock.drv.local_path.return_value.\
            drv._resize_volume_file.return_value.\
            drv.extend_volume
        drv.extend_volume.return_value = None
        self.assertIsNone(mock.drv.local_path().
                          drv._resize_volume_file().
                          drv.extend_volume(
                              self.TEST_LOCAL_PATH,
                              self.TEST_EXTEND_SIZE_IN_GB))

    def test_delete_snapfiles(self):
        """Delete_snapfiles assert test case."""

        drv = self._driver
        mock = self._mock

        drv._delete_snapfiles = mock.drv._run_ssh.return_value.\
            drv._execute.return_value.\
            drv._delete_snapfiles
        drv._delete_snapfiles.return_value = None
        self.assertIsNone(mock.drv._run_ssh().
                          drv._execute().
                          drv._delete_snapfiles(
                              self.TEST_VOLUME_PATH,
                              self.TEST_MNT_POINT))

    def test_delete_volume_no_provider_location(self):
        """Delete volume with no provider location specified."""

        drv = self._driver

        volume = FakeEnv()
        volume['name'] = 'volume-123'
        volume['provider_location'] = None

        result = drv.delete_volume(volume)
        self.assertIsNone(result)

    def test_delete_volume(self):
        """Delete volume test case."""

        drv = self._driver
        mock = self._mock

        volume = FakeEnv()
        volume['id'] = '123'
        volume['provider_location'] = self.TEST_NFS_EXPORT

        drv.delete_volume = mock.drv._get_export_path.return_value.\
            drv._delete_snapfiles.return_value.drv.delete_volume
        drv.delete_volume.return_value = True
        self.assertEqual(True, mock.drv._get_export_path(volume['id']).
                         drv._delete_snapfiles(
                             self.TEST_VOLUME_PATH,
                             self.TEST_MNT_POINT).
                         drv.delete_volume(volume))

    def test_create_snapshot(self):
        """Create snapshot simple test case."""

        drv = self._driver
        mock = self._mock

        volume = FakeEnv()
        volume['id'] = '123'
        volume['name'] = 'volume-123'

        snapshot = FakeEnv()
        snapshot['volume_id'] = volume['id']
        snapshot['volume_name'] = 'volume-123'
        snapshot.name = 'snapshot-123'

        drv.create_snapshot = mock.drv._get_export_path.return_value.\
            drv._get_provider_location.return_value.\
            drv._get_mount_point_for_share.return_value.\
            drv._create_ibmnas_snap.return_value.\
            drv.create_snapshot
        drv.create_snapshot.return_value = None
        self.assertIsNone(mock.drv._get_export_path(snapshot['volume_id']).
                          drv._get_provider_location(snapshot['volume_id']).
                          drv._get_mount_point_for_share(self.TEST_NFS_EXPORT).
                          drv._create_ibmnas_snap(
                              src=self.TEST_VOLUME_PATH,
                              dest=self.TEST_SNAP_PATH,
                              mount_path=self.TEST_MNT_POINT).
                          drv.create_snapshot(snapshot))

    def test_delete_snapshot(self):
        """Delete snapshot simple test case."""

        drv = self._driver
        mock = self._mock

        volume = FakeEnv()
        volume['id'] = '123'
        volume['provider_location'] = self.TEST_NFS_EXPORT

        snapshot = FakeEnv()
        snapshot['volume_id'] = volume['id']
        snapshot['volume_name'] = 'volume-123'
        snapshot['name'] = 'snapshot-123'

        drv.delete_snapshot = mock.drv._get_provider_location.return_value.\
            drv._get_mount_point_for_share.return_value.drv._execute.\
            return_value.drv.delete_snapshot
        drv.delete_snapshot.return_value = None
        self.assertIsNone(mock.drv._get_provider_location(volume['id']).
                          drv._get_mount_point_for_share(self.TEST_NFS_EXPORT).
                          drv._execute().
                          drv.delete_snapshot(snapshot))

    def test_create_cloned_volume(self):
        """Clone volume with equal size test case."""

        drv = self._driver
        mock = self._mock

        volume_src = FakeEnv()
        volume_src['id'] = '123'
        volume_src['name'] = 'volume-123'
        volume_src.size = self.TEST_SIZE_IN_GB

        volume_dest = FakeEnv()
        volume_dest['id'] = '456'
        volume_dest['name'] = 'volume-456'
        volume_dest['size'] = self.TEST_SIZE_IN_GB
        volume_dest.size = self.TEST_SIZE_IN_GB

        drv.create_cloned_volume = mock.drv._get_export_path.\
            return_value.drv._create_ibmnas_copy.return_value.\
            drv._find_share.return_value.\
            drv._set_rw_permissions_for_all.return_value.\
            drv._resize_volume_file.return_value.\
            drv.create_cloned_volume
        drv.create_cloned_volume.return_value = self.TEST_NFS_EXPORT
        self.assertEqual(self.TEST_NFS_EXPORT,
                         mock.drv._get_export_path(volume_src['id']).
                         drv._create_ibmnas_copy().
                         drv._find_share().
                         drv._set_rw_permissions_for_all().
                         drv._resize_volume_file().
                         drv.create_cloned_volume(
                             volume_dest,
                             volume_src))

    def test_create_volume_from_snapshot(self):
        """Create volume from snapshot test case."""

        drv = self._driver
        mock = self._mock

        volume = FakeEnv()
        volume['id'] = '123'
        volume['name'] = 'volume-123'
        volume['size'] = self.TEST_SIZE_IN_GB

        snapshot = FakeEnv()
        snapshot['volume_id'] = volume['id']
        snapshot['volume_name'] = 'volume-123'
        snapshot['volume_size'] = self.TEST_SIZE_IN_GB
        snapshot.name = 'snapshot-123'

        drv.create_volume_from_snapshot = mock.drv._get_export_path.\
            return_value.drv._create_ibmnas_snap.return_value.\
            drv._find_share.return_value.\
            drv._set_rw_permissions_for_all.return_value.\
            drv._resize_volume_file.return_value.\
            drv.create_volume_from_snapshot
        drv.create_volume_from_snapshot.return_value = self.TEST_NFS_EXPORT
        self.assertEqual(self.TEST_NFS_EXPORT,
                         mock.drv._get_export_path(volume['id']).
                         drv._create_ibmnas_snap().
                         drv._find_share().
                         drv._set_rw_permissions_for_all().
                         drv._resize_volume_file().
                         drv.create_volume_from_snapshot(snapshot))
