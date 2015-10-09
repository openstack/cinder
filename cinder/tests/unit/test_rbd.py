
# Copyright 2012 Josh Durgin
# Copyright 2013 Canonical Ltd.
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


import math
import os
import tempfile

import mock
from oslo_utils import timeutils
from oslo_utils import units

from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder.image import image_utils
from cinder import test
from cinder.tests.unit.image import fake as fake_image
from cinder.tests.unit import test_volume
from cinder.tests.unit import utils
from cinder.volume import configuration as conf
import cinder.volume.drivers.rbd as driver
from cinder.volume.flows.manager import create_volume


# This is used to collect raised exceptions so that tests may check what was
# raised.
# NOTE: this must be initialised in test setUp().
RAISED_EXCEPTIONS = []


class MockException(Exception):

    def __init__(self, *args, **kwargs):
        RAISED_EXCEPTIONS.append(self.__class__)


class MockImageNotFoundException(MockException):
    """Used as mock for rbd.ImageNotFound."""


class MockImageBusyException(MockException):
    """Used as mock for rbd.ImageBusy."""


class MockImageExistsException(MockException):
    """Used as mock for rbd.ImageExists."""


def common_mocks(f):
    """Decorator to set mocks common to all tests.

    The point of doing these mocks here is so that we don't accidentally set
    mocks that can't/don't get unset.
    """
    def _common_inner_inner1(inst, *args, **kwargs):
        @mock.patch('cinder.volume.drivers.rbd.RBDVolumeProxy')
        @mock.patch('cinder.volume.drivers.rbd.RADOSClient')
        @mock.patch('cinder.backup.drivers.ceph.rbd')
        @mock.patch('cinder.backup.drivers.ceph.rados')
        def _common_inner_inner2(mock_rados, mock_rbd, mock_client,
                                 mock_proxy):
            inst.mock_rbd = mock_rbd
            inst.mock_rados = mock_rados
            inst.mock_client = mock_client
            inst.mock_proxy = mock_proxy
            inst.mock_rbd.RBD.Error = Exception
            inst.mock_rados.Error = Exception
            inst.mock_rbd.ImageBusy = MockImageBusyException
            inst.mock_rbd.ImageNotFound = MockImageNotFoundException
            inst.mock_rbd.ImageExists = MockImageExistsException

            inst.driver.rbd = inst.mock_rbd
            inst.driver.rados = inst.mock_rados
            return f(inst, *args, **kwargs)

        return _common_inner_inner2()

    return _common_inner_inner1


CEPH_MON_DUMP = """dumped monmap epoch 1
{ "epoch": 1,
  "fsid": "33630410-6d93-4d66-8e42-3b953cf194aa",
  "modified": "2013-05-22 17:44:56.343618",
  "created": "2013-05-22 17:44:56.343618",
  "mons": [
        { "rank": 0,
          "name": "a",
          "addr": "[::1]:6789\/0"},
        { "rank": 1,
          "name": "b",
          "addr": "[::1]:6790\/0"},
        { "rank": 2,
          "name": "c",
          "addr": "[::1]:6791\/0"},
        { "rank": 3,
          "name": "d",
          "addr": "127.0.0.1:6792\/0"},
        { "rank": 4,
          "name": "e",
          "addr": "example.com:6791\/0"}],
  "quorum": [
        0,
        1,
        2]}
"""


class RBDTestCase(test.TestCase):

    def setUp(self):
        global RAISED_EXCEPTIONS
        RAISED_EXCEPTIONS = []
        super(RBDTestCase, self).setUp()

        self.cfg = mock.Mock(spec=conf.Configuration)
        self.cfg.volume_tmp_dir = None
        self.cfg.image_conversion_dir = None
        self.cfg.rbd_cluster_name = 'nondefault'
        self.cfg.rbd_pool = 'rbd'
        self.cfg.rbd_ceph_conf = None
        self.cfg.rbd_secret_uuid = None
        self.cfg.rbd_user = None
        self.cfg.volume_dd_blocksize = '1M'
        self.cfg.rbd_store_chunk_size = 4

        mock_exec = mock.Mock()
        mock_exec.return_value = ('', '')

        self.driver = driver.RBDDriver(execute=mock_exec,
                                       configuration=self.cfg)
        self.driver.set_initialized()

        self.volume_name = u'volume-00000001'
        self.snapshot_name = u'snapshot-00000001'
        self.volume_size = 1
        self.volume = dict(name=self.volume_name, size=self.volume_size)
        self.snapshot = dict(volume_name=self.volume_name,
                             name=self.snapshot_name)

    @common_mocks
    def test_create_volume(self):
        client = self.mock_client.return_value
        client.__enter__.return_value = client

        self.driver.create_volume(self.volume)

        chunk_size = self.cfg.rbd_store_chunk_size * units.Mi
        order = int(math.log(chunk_size, 2))
        args = [client.ioctx, str(self.volume_name),
                self.volume_size * units.Gi, order]
        kwargs = {'old_format': False,
                  'features': client.features}
        self.mock_rbd.RBD.return_value.create.assert_called_once_with(
            *args, **kwargs)
        client.__enter__.assert_called_once_with()
        client.__exit__.assert_called_once_with(None, None, None)

    @common_mocks
    def test_manage_existing_get_size(self):
        with mock.patch.object(self.driver.rbd.Image(), 'size') as \
                mock_rbd_image_size:
            with mock.patch.object(self.driver.rbd.Image(), 'close') \
                    as mock_rbd_image_close:
                mock_rbd_image_size.return_value = 2 * units.Gi
                existing_ref = {'source-name': self.volume_name}
                return_size = self.driver.manage_existing_get_size(
                    self.volume,
                    existing_ref)
                self.assertEqual(2, return_size)
                mock_rbd_image_size.assert_called_once_with()
                mock_rbd_image_close.assert_called_once_with()

    @common_mocks
    def test_manage_existing_get_invalid_size(self):

        with mock.patch.object(self.driver.rbd.Image(), 'size') as \
                mock_rbd_image_size:
            with mock.patch.object(self.driver.rbd.Image(), 'close') \
                    as mock_rbd_image_close:
                mock_rbd_image_size.return_value = 'abcd'
                existing_ref = {'source-name': self.volume_name}
                self.assertRaises(exception.VolumeBackendAPIException,
                                  self.driver.manage_existing_get_size,
                                  self.volume, existing_ref)

                mock_rbd_image_size.assert_called_once_with()
                mock_rbd_image_close.assert_called_once_with()

    @common_mocks
    def test_manage_existing(self):
        client = self.mock_client.return_value
        client.__enter__.return_value = client

        with mock.patch.object(self.driver.rbd.RBD(), 'rename') as \
                mock_rbd_image_rename:
            exist_volume = 'vol-exist'
            existing_ref = {'source-name': exist_volume}
            mock_rbd_image_rename.return_value = 0
            self.driver.manage_existing(self.volume, existing_ref)
            mock_rbd_image_rename.assert_called_with(
                client.ioctx,
                exist_volume,
                self.volume_name)

    @common_mocks
    def test_manage_existing_with_exist_rbd_image(self):
        client = self.mock_client.return_value
        client.__enter__.return_value = client

        self.mock_rbd.RBD.return_value.rename.side_effect = (
            MockImageExistsException)

        exist_volume = 'vol-exist'
        existing_ref = {'source-name': exist_volume}
        self.assertRaises(self.mock_rbd.ImageExists,
                          self.driver.manage_existing,
                          self.volume, existing_ref)

        # Make sure the exception was raised
        self.assertEqual(RAISED_EXCEPTIONS,
                         [self.mock_rbd.ImageExists])

    @common_mocks
    def test_delete_backup_snaps(self):
        self.driver.rbd.Image.remove_snap = mock.Mock()
        with mock.patch.object(self.driver, '_get_backup_snaps') as \
                mock_get_backup_snaps:
            mock_get_backup_snaps.return_value = [{'name': 'snap1'}]
            rbd_image = self.driver.rbd.Image()
            self.driver._delete_backup_snaps(rbd_image)
            mock_get_backup_snaps.assert_called_once_with(rbd_image)
            self.assertTrue(
                self.driver.rbd.Image.return_value.remove_snap.called)

    @common_mocks
    def test_delete_volume(self):
        client = self.mock_client.return_value

        self.driver.rbd.Image.return_value.list_snaps.return_value = []

        with mock.patch.object(self.driver, '_get_clone_info') as \
                mock_get_clone_info:
            with mock.patch.object(self.driver, '_delete_backup_snaps') as \
                    mock_delete_backup_snaps:
                mock_get_clone_info.return_value = (None, None, None)

                self.driver.delete_volume(self.volume)

                mock_get_clone_info.assert_called_once_with(
                    self.mock_rbd.Image.return_value,
                    self.volume_name,
                    None)
                (self.driver.rbd.Image.return_value
                    .list_snaps.assert_called_once_with())
                client.__enter__.assert_called_once_with()
                client.__exit__.assert_called_once_with(None, None, None)
                mock_delete_backup_snaps.assert_called_once_with(
                    self.mock_rbd.Image.return_value)
                self.assertFalse(
                    self.driver.rbd.Image.return_value.unprotect_snap.called)
                self.assertEqual(
                    1, self.driver.rbd.RBD.return_value.remove.call_count)

    @common_mocks
    def delete_volume_not_found(self):
        self.mock_rbd.Image.side_effect = self.mock_rbd.ImageNotFound
        self.assertIsNone(self.driver.delete_volume(self.volume))
        self.mock_rbd.Image.assert_called_once_with()
        # Make sure the exception was raised
        self.assertEqual(RAISED_EXCEPTIONS, [self.mock_rbd.ImageNotFound])

    @common_mocks
    def test_delete_busy_volume(self):
        self.mock_rbd.Image.return_value.list_snaps.return_value = []

        self.mock_rbd.RBD.return_value.remove.side_effect = (
            self.mock_rbd.ImageBusy)

        with mock.patch.object(self.driver, '_get_clone_info') as \
                mock_get_clone_info:
            mock_get_clone_info.return_value = (None, None, None)
            with mock.patch.object(self.driver, '_delete_backup_snaps') as \
                    mock_delete_backup_snaps:
                with mock.patch.object(driver, 'RADOSClient') as \
                        mock_rados_client:
                    self.assertRaises(exception.VolumeIsBusy,
                                      self.driver.delete_volume, self.volume)

                    mock_get_clone_info.assert_called_once_with(
                        self.mock_rbd.Image.return_value,
                        self.volume_name,
                        None)
                    (self.mock_rbd.Image.return_value.list_snaps
                     .assert_called_once_with())
                    mock_rados_client.assert_called_once_with(self.driver)
                    mock_delete_backup_snaps.assert_called_once_with(
                        self.mock_rbd.Image.return_value)
                    self.assertFalse(
                        self.mock_rbd.Image.return_value.unprotect_snap.called)
                    self.assertEqual(
                        3, self.mock_rbd.RBD.return_value.remove.call_count)
                    self.assertEqual(3, len(RAISED_EXCEPTIONS))
                    # Make sure the exception was raised
                    self.assertIn(self.mock_rbd.ImageBusy, RAISED_EXCEPTIONS)

    @common_mocks
    def test_delete_volume_not_found(self):
        self.mock_rbd.Image.return_value.list_snaps.return_value = []

        self.mock_rbd.RBD.return_value.remove.side_effect = (
            self.mock_rbd.ImageNotFound)

        with mock.patch.object(self.driver, '_get_clone_info') as \
                mock_get_clone_info:
            mock_get_clone_info.return_value = (None, None, None)
            with mock.patch.object(self.driver, '_delete_backup_snaps') as \
                    mock_delete_backup_snaps:
                with mock.patch.object(driver, 'RADOSClient') as \
                        mock_rados_client:
                    self.assertIsNone(self.driver.delete_volume(self.volume))
                    mock_get_clone_info.assert_called_once_with(
                        self.mock_rbd.Image.return_value,
                        self.volume_name,
                        None)
                    (self.mock_rbd.Image.return_value.list_snaps
                     .assert_called_once_with())
                    mock_rados_client.assert_called_once_with(self.driver)
                    mock_delete_backup_snaps.assert_called_once_with(
                        self.mock_rbd.Image.return_value)
                    self.assertFalse(
                        self.mock_rbd.Image.return_value.unprotect_snap.called)
                    self.assertEqual(
                        1, self.mock_rbd.RBD.return_value.remove.call_count)
                    # Make sure the exception was raised
                    self.assertEqual(RAISED_EXCEPTIONS,
                                     [self.mock_rbd.ImageNotFound])

    @common_mocks
    def test_create_snapshot(self):
        proxy = self.mock_proxy.return_value
        proxy.__enter__.return_value = proxy

        self.driver.create_snapshot(self.snapshot)

        args = [str(self.snapshot_name)]
        proxy.create_snap.assert_called_with(*args)
        proxy.protect_snap.assert_called_with(*args)

    @common_mocks
    def test_delete_snapshot(self):
        proxy = self.mock_proxy.return_value
        proxy.__enter__.return_value = proxy

        self.driver.delete_snapshot(self.snapshot)

        proxy.remove_snap.assert_called_with(self.snapshot_name)
        proxy.unprotect_snap.assert_called_with(self.snapshot_name)

    @common_mocks
    def test_delete_busy_snapshot(self):
        proxy = self.mock_proxy.return_value
        proxy.__enter__.return_value = proxy

        proxy.unprotect_snap.side_effect = (
            self.mock_rbd.ImageBusy)

        with mock.patch.object(self.driver, '_get_children_info') as \
                mock_get_children_info:
            mock_get_children_info.return_value = [('pool', 'volume2')]

            with mock.patch.object(driver, 'LOG') as \
                    mock_log:

                self.assertRaises(exception.SnapshotIsBusy,
                                  self.driver.delete_snapshot,
                                  self.snapshot)

                mock_get_children_info.assert_called_once_with(
                    proxy,
                    self.snapshot_name)

                self.assertTrue(mock_log.info.called)
                self.assertTrue(proxy.unprotect_snap.called)
                self.assertFalse(proxy.remove_snap.called)

    @common_mocks
    def test_get_children_info(self):
        volume = self.mock_proxy
        volume.set_snap = mock.Mock()
        volume.list_children = mock.Mock()
        list_children = [('pool', 'volume2')]
        volume.list_children.return_value = list_children

        info = self.driver._get_children_info(volume,
                                              self.snapshot_name)

        self.assertEqual(list_children, info)

    @common_mocks
    def test_get_clone_info(self):
        volume = self.mock_rbd.Image()
        volume.set_snap = mock.Mock()
        volume.parent_info = mock.Mock()
        parent_info = ('a', 'b', '%s.clone_snap' % (self.volume_name))
        volume.parent_info.return_value = parent_info

        info = self.driver._get_clone_info(volume, self.volume_name)

        self.assertEqual(parent_info, info)

        self.assertFalse(volume.set_snap.called)
        volume.parent_info.assert_called_once_with()

    @common_mocks
    def test_get_clone_info_w_snap(self):
        volume = self.mock_rbd.Image()
        volume.set_snap = mock.Mock()
        volume.parent_info = mock.Mock()
        parent_info = ('a', 'b', '%s.clone_snap' % (self.volume_name))
        volume.parent_info.return_value = parent_info

        snapshot = self.mock_rbd.ImageSnapshot()

        info = self.driver._get_clone_info(volume, self.volume_name,
                                           snap=snapshot)

        self.assertEqual(parent_info, info)

        self.assertEqual(2, volume.set_snap.call_count)
        volume.parent_info.assert_called_once_with()

    @common_mocks
    def test_get_clone_info_w_exception(self):
        volume = self.mock_rbd.Image()
        volume.set_snap = mock.Mock()
        volume.parent_info = mock.Mock()
        volume.parent_info.side_effect = self.mock_rbd.ImageNotFound

        snapshot = self.mock_rbd.ImageSnapshot()

        info = self.driver._get_clone_info(volume, self.volume_name,
                                           snap=snapshot)

        self.assertEqual((None, None, None), info)

        self.assertEqual(2, volume.set_snap.call_count)
        volume.parent_info.assert_called_once_with()
        # Make sure the exception was raised
        self.assertEqual(RAISED_EXCEPTIONS, [self.mock_rbd.ImageNotFound])

    @common_mocks
    def test_get_clone_info_deleted_volume(self):
        volume = self.mock_rbd.Image()
        volume.set_snap = mock.Mock()
        volume.parent_info = mock.Mock()
        parent_info = ('a', 'b', '%s.clone_snap' % (self.volume_name))
        volume.parent_info.return_value = parent_info

        info = self.driver._get_clone_info(volume,
                                           "%s.deleted" % (self.volume_name))

        self.assertEqual(parent_info, info)

        self.assertFalse(volume.set_snap.called)
        volume.parent_info.assert_called_once_with()

    @common_mocks
    def test_create_cloned_volume_same_size(self):
        src_name = u'volume-00000001'
        dst_name = u'volume-00000002'

        self.cfg.rbd_max_clone_depth = 2

        with mock.patch.object(self.driver, '_get_clone_depth') as \
                mock_get_clone_depth:
            # Try with no flatten required
            with mock.patch.object(self.driver, '_resize') as mock_resize:
                mock_get_clone_depth.return_value = 1

                self.driver.create_cloned_volume({'name': dst_name,
                                                  'size': 10},
                                                 {'name': src_name,
                                                  'size': 10})

                (self.mock_rbd.Image.return_value.create_snap
                    .assert_called_once_with('.'.join((dst_name,
                                                       'clone_snap'))))
                (self.mock_rbd.Image.return_value.protect_snap
                    .assert_called_once_with('.'.join((dst_name,
                                                       'clone_snap'))))
                self.assertEqual(
                    1, self.mock_rbd.RBD.return_value.clone.call_count)
                self.mock_rbd.Image.return_value.close \
                    .assert_called_once_with()
                self.assertTrue(mock_get_clone_depth.called)
                self.assertEqual(
                    0, mock_resize.call_count)

    @common_mocks
    def test_create_cloned_volume_different_size(self):
        src_name = u'volume-00000001'
        dst_name = u'volume-00000002'

        self.cfg.rbd_max_clone_depth = 2

        with mock.patch.object(self.driver, '_get_clone_depth') as \
                mock_get_clone_depth:
            # Try with no flatten required
            with mock.patch.object(self.driver, '_resize') as mock_resize:
                mock_get_clone_depth.return_value = 1

                self.driver.create_cloned_volume({'name': dst_name,
                                                  'size': 20},
                                                 {'name': src_name,
                                                  'size': 10})

                (self.mock_rbd.Image.return_value.create_snap
                    .assert_called_once_with('.'.join((dst_name,
                                                       'clone_snap'))))
                (self.mock_rbd.Image.return_value.protect_snap
                    .assert_called_once_with('.'.join((dst_name,
                                                       'clone_snap'))))
                self.assertEqual(
                    1, self.mock_rbd.RBD.return_value.clone.call_count)
                self.mock_rbd.Image.return_value.close \
                    .assert_called_once_with()
                self.assertTrue(mock_get_clone_depth.called)
                self.assertEqual(
                    1, mock_resize.call_count)

    @common_mocks
    def test_create_cloned_volume_w_flatten(self):
        src_name = u'volume-00000001'
        dst_name = u'volume-00000002'

        self.cfg.rbd_max_clone_depth = 1

        with mock.patch.object(self.driver, '_get_clone_info') as \
                mock_get_clone_info:
            mock_get_clone_info.return_value = (
                ('fake_pool', dst_name, '.'.join((dst_name, 'clone_snap'))))
            with mock.patch.object(self.driver, '_get_clone_depth') as \
                    mock_get_clone_depth:
                # Try with no flatten required
                mock_get_clone_depth.return_value = 1

                self.assertRaises(self.mock_rbd.RBD.Error,
                                  self.driver.create_cloned_volume,
                                  dict(name=dst_name), dict(name=src_name))

                (self.mock_rbd.Image.return_value.create_snap
                 .assert_called_once_with('.'.join((dst_name, 'clone_snap'))))
                (self.mock_rbd.Image.return_value.protect_snap
                 .assert_called_once_with('.'.join((dst_name, 'clone_snap'))))
                self.assertEqual(
                    1, self.mock_rbd.RBD.return_value.clone.call_count)
                (self.mock_rbd.Image.return_value.unprotect_snap
                 .assert_called_once_with('.'.join((dst_name, 'clone_snap'))))
                (self.mock_rbd.Image.return_value.remove_snap
                 .assert_called_once_with('.'.join((dst_name, 'clone_snap'))))

                # We expect the driver to close both volumes, so 2 is expected
                self.assertEqual(
                    2, self.mock_rbd.Image.return_value.close.call_count)
                self.assertTrue(mock_get_clone_depth.called)

    @common_mocks
    def test_create_cloned_volume_w_clone_exception(self):
        src_name = u'volume-00000001'
        dst_name = u'volume-00000002'

        self.cfg.rbd_max_clone_depth = 2
        self.mock_rbd.RBD.return_value.clone.side_effect = (
            self.mock_rbd.RBD.Error)
        with mock.patch.object(self.driver, '_get_clone_depth') as \
                mock_get_clone_depth:
            # Try with no flatten required
            mock_get_clone_depth.return_value = 1

            self.assertRaises(self.mock_rbd.RBD.Error,
                              self.driver.create_cloned_volume,
                              {'name': dst_name}, {'name': src_name})

            (self.mock_rbd.Image.return_value.create_snap
                .assert_called_once_with('.'.join((dst_name, 'clone_snap'))))
            (self.mock_rbd.Image.return_value.protect_snap
                .assert_called_once_with('.'.join((dst_name, 'clone_snap'))))
            self.assertEqual(
                1, self.mock_rbd.RBD.return_value.clone.call_count)
            (self.mock_rbd.Image.return_value.unprotect_snap
             .assert_called_once_with('.'.join((dst_name, 'clone_snap'))))
            (self.mock_rbd.Image.return_value.remove_snap
                .assert_called_once_with('.'.join((dst_name, 'clone_snap'))))
            self.mock_rbd.Image.return_value.close.assert_called_once_with()

    @common_mocks
    def test_good_locations(self):
        locations = ['rbd://fsid/pool/image/snap',
                     'rbd://%2F/%2F/%2F/%2F', ]
        map(self.driver._parse_location, locations)

    @common_mocks
    def test_bad_locations(self):
        locations = ['rbd://image',
                     'http://path/to/somewhere/else',
                     'rbd://image/extra',
                     'rbd://image/',
                     'rbd://fsid/pool/image/',
                     'rbd://fsid/pool/image/snap/',
                     'rbd://///', ]
        for loc in locations:
            self.assertRaises(exception.ImageUnacceptable,
                              self.driver._parse_location,
                              loc)
            self.assertFalse(
                self.driver._is_cloneable(loc, {'disk_format': 'raw'}))

    @common_mocks
    def test_cloneable(self):
        with mock.patch.object(self.driver, '_get_fsid') as mock_get_fsid:
            mock_get_fsid.return_value = 'abc'
            location = 'rbd://abc/pool/image/snap'
            info = {'disk_format': 'raw'}
            self.assertTrue(self.driver._is_cloneable(location, info))
            self.assertTrue(mock_get_fsid.called)

    @common_mocks
    def test_uncloneable_different_fsid(self):
        with mock.patch.object(self.driver, '_get_fsid') as mock_get_fsid:
            mock_get_fsid.return_value = 'abc'
            location = 'rbd://def/pool/image/snap'
            self.assertFalse(
                self.driver._is_cloneable(location, {'disk_format': 'raw'}))
            self.assertTrue(mock_get_fsid.called)

    @common_mocks
    def test_uncloneable_unreadable(self):
        with mock.patch.object(self.driver, '_get_fsid') as mock_get_fsid:
            mock_get_fsid.return_value = 'abc'
            location = 'rbd://abc/pool/image/snap'

            self.driver.rbd.Error = Exception
            self.mock_proxy.side_effect = Exception

            args = [location, {'disk_format': 'raw'}]
            self.assertFalse(self.driver._is_cloneable(*args))
            self.assertEqual(1, self.mock_proxy.call_count)
            self.assertTrue(mock_get_fsid.called)

    @common_mocks
    def test_uncloneable_bad_format(self):
        with mock.patch.object(self.driver, '_get_fsid') as mock_get_fsid:
            mock_get_fsid.return_value = 'abc'
            location = 'rbd://abc/pool/image/snap'
            formats = ['qcow2', 'vmdk', 'vdi']
            for f in formats:
                self.assertFalse(
                    self.driver._is_cloneable(location, {'disk_format': f}))
            self.assertTrue(mock_get_fsid.called)

    def _copy_image(self):
        with mock.patch.object(tempfile, 'NamedTemporaryFile'):
            with mock.patch.object(os.path, 'exists') as mock_exists:
                mock_exists.return_value = True
                with mock.patch.object(image_utils, 'fetch_to_raw'):
                    with mock.patch.object(self.driver, 'delete_volume'):
                        with mock.patch.object(self.driver, '_resize'):
                            mock_image_service = mock.MagicMock()
                            args = [None, {'name': 'test', 'size': 1},
                                    mock_image_service, None]
                            self.driver.copy_image_to_volume(*args)

    @common_mocks
    def test_copy_image_no_volume_tmp(self):
        self.cfg.volume_tmp_dir = None
        self.cfg.image_conversion_dir = None
        self._copy_image()

    @common_mocks
    def test_copy_image_volume_tmp(self):
        self.cfg.volume_tmp_dir = None
        self.cfg.image_conversion_dir = '/var/run/cinder/tmp'
        self._copy_image()

    @common_mocks
    def test_update_volume_stats(self):
        client = self.mock_client.return_value
        client.__enter__.return_value = client

        client.cluster = mock.Mock()
        client.cluster.mon_command = mock.Mock()
        client.cluster.mon_command.return_value = (
            0, '{"stats":{"total_bytes":64385286144,'
            '"total_used_bytes":3289628672,"total_avail_bytes":61095657472},'
            '"pools":[{"name":"rbd","id":2,"stats":{"kb_used":1510197,'
            '"bytes_used":1546440971,"max_avail":28987613184,"objects":412}},'
            '{"name":"volumes","id":3,"stats":{"kb_used":0,"bytes_used":0,'
            '"max_avail":28987613184,"objects":0}}]}\n', '')
        self.driver.configuration.safe_get = mock.Mock()
        self.driver.configuration.safe_get.return_value = 'RBD'

        expected = dict(
            volume_backend_name='RBD',
            vendor_name='Open Source',
            driver_version=self.driver.VERSION,
            storage_protocol='ceph',
            total_capacity_gb=27,
            free_capacity_gb=26,
            reserved_percentage=0)

        actual = self.driver.get_volume_stats(True)
        client.cluster.mon_command.assert_called_once_with(
            '{"prefix":"df", "format":"json"}', '')
        self.assertDictMatch(expected, actual)

    @common_mocks
    def test_update_volume_stats_error(self):
        client = self.mock_client.return_value
        client.__enter__.return_value = client

        client.cluster = mock.Mock()
        client.cluster.mon_command = mock.Mock()
        client.cluster.mon_command.return_value = (22, '', '')

        self.driver.configuration.safe_get = mock.Mock()
        self.driver.configuration.safe_get.return_value = 'RBD'

        expected = dict(volume_backend_name='RBD',
                        vendor_name='Open Source',
                        driver_version=self.driver.VERSION,
                        storage_protocol='ceph',
                        total_capacity_gb='unknown',
                        free_capacity_gb='unknown',
                        reserved_percentage=0)

        actual = self.driver.get_volume_stats(True)
        client.cluster.mon_command.assert_called_once_with(
            '{"prefix":"df", "format":"json"}', '')
        self.assertDictMatch(expected, actual)

    @common_mocks
    def test_get_mon_addrs(self):
        with mock.patch.object(self.driver, '_execute') as mock_execute:
            mock_execute.return_value = (CEPH_MON_DUMP, '')
            hosts = ['::1', '::1', '::1', '127.0.0.1', 'example.com']
            ports = ['6789', '6790', '6791', '6792', '6791']
            self.assertEqual((hosts, ports), self.driver._get_mon_addrs())

    @common_mocks
    def test_initialize_connection(self):
        hosts = ['::1', '::1', '::1', '127.0.0.1', 'example.com']
        ports = ['6789', '6790', '6791', '6792', '6791']

        with mock.patch.object(self.driver, '_get_mon_addrs') as \
                mock_get_mon_addrs:
            mock_get_mon_addrs.return_value = (hosts, ports)

            volume_id = '0a83f0a3-ef6e-47b6-a8aa-20436bc9ed01'
            expected = {
                'driver_volume_type': 'rbd',
                'data': {
                    'name': '%s/%s' % (self.cfg.rbd_pool,
                                       self.volume_name),
                    'hosts': hosts,
                    'ports': ports,
                    'auth_enabled': False,
                    'auth_username': None,
                    'secret_type': 'ceph',
                    'secret_uuid': None,
                    'volume_id': volume_id
                }
            }
            volume = dict(name=self.volume_name, id=volume_id)
            actual = self.driver.initialize_connection(volume, None)
            self.assertDictMatch(expected, actual)
            self.assertTrue(mock_get_mon_addrs.called)

    @common_mocks
    def test_clone(self):
        src_pool = u'images'
        src_image = u'image-name'
        src_snap = u'snapshot-name'

        client_stack = []

        def mock__enter__(inst):
            def _inner():
                client_stack.append(inst)
                return inst
            return _inner

        client = self.mock_client.return_value
        # capture both rados client used to perform the clone
        client.__enter__.side_effect = mock__enter__(client)

        self.driver._clone(self.volume, src_pool, src_image, src_snap)

        args = [client_stack[0].ioctx, str(src_image), str(src_snap),
                client_stack[1].ioctx, str(self.volume_name)]
        kwargs = {'features': client.features}
        self.mock_rbd.RBD.return_value.clone.assert_called_once_with(
            *args, **kwargs)
        self.assertEqual(2, client.__enter__.call_count)

    @common_mocks
    def test_extend_volume(self):
        fake_size = '20'
        fake_vol = {'project_id': 'testprjid', 'name': self.volume_name,
                    'size': fake_size,
                    'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66'}

        self.mox.StubOutWithMock(self.driver, '_resize')
        size = int(fake_size) * units.Gi
        self.driver._resize(fake_vol, size=size)

        self.mox.ReplayAll()
        self.driver.extend_volume(fake_vol, fake_size)

        self.mox.VerifyAll()

    @common_mocks
    def test_retype(self):
        context = {}
        diff = {'encryption': {},
                'extra_specs': {}}
        fake_volume = {'name': 'testvolume',
                       'host': 'currenthost'}
        fake_type = 'high-IOPS'

        # no support for migration
        host = {'host': 'anotherhost'}
        self.assertFalse(self.driver.retype(context, fake_volume,
                                            fake_type, diff, host))
        host = {'host': 'currenthost'}

        # no support for changing encryption
        diff['encryption'] = {'non-empty': 'non-empty'}
        self.assertFalse(self.driver.retype(context, fake_volume,
                                            fake_type, diff, host))
        diff['encryption'] = {}

        # no support for changing extra_specs
        diff['extra_specs'] = {'non-empty': 'non-empty'}
        self.assertFalse(self.driver.retype(context, fake_volume,
                                            fake_type, diff, host))
        diff['extra_specs'] = {}

        self.assertTrue(self.driver.retype(context, fake_volume,
                                           fake_type, diff, host))

    @common_mocks
    def test_update_migrated_volume(self):
        client = self.mock_client.return_value
        client.__enter__.return_value = client

        with mock.patch.object(self.driver.rbd.RBD(), 'rename') as mock_rename:
            context = {}
            current_volume = {'id': 'curr_id',
                              'name': 'curr_name',
                              'provider_location': 'curr_provider_location'}
            original_volume = {'id': 'orig_id',
                               'name': 'orig_name',
                               'provider_location': 'orig_provider_location'}
            mock_rename.return_value = 0
            model_update = self.driver.update_migrated_volume(context,
                                                              original_volume,
                                                              current_volume,
                                                              'available')
            mock_rename.assert_called_with(client.ioctx,
                                           'volume-%s' % current_volume['id'],
                                           'volume-%s' % original_volume['id'])
            self.assertEqual({'_name_id': None,
                              'provider_location': None}, model_update)

    def test_rbd_volume_proxy_init(self):
        mock_driver = mock.Mock(name='driver')
        mock_driver._connect_to_rados.return_value = (None, None)
        with driver.RBDVolumeProxy(mock_driver, self.volume_name):
            self.assertEqual(1, mock_driver._connect_to_rados.call_count)
            self.assertFalse(mock_driver._disconnect_from_rados.called)

        self.assertEqual(1, mock_driver._disconnect_from_rados.call_count)

        mock_driver.reset_mock()

        snap = u'snapshot-name'
        with driver.RBDVolumeProxy(mock_driver, self.volume_name,
                                   snapshot=snap):
            self.assertEqual(1, mock_driver._connect_to_rados.call_count)
            self.assertFalse(mock_driver._disconnect_from_rados.called)

        self.assertEqual(1, mock_driver._disconnect_from_rados.call_count)

    @common_mocks
    @mock.patch('time.sleep')
    def test_connect_to_rados(self, sleep_mock):
        # Default
        self.cfg.rados_connect_timeout = -1

        self.mock_rados.Rados.return_value.open_ioctx.return_value = \
            self.mock_rados.Rados.return_value.ioctx

        # default configured pool
        ret = self.driver._connect_to_rados()
        self.assertTrue(self.mock_rados.Rados.return_value.connect.called)
        # Expect no timeout if default is used
        self.mock_rados.Rados.return_value.connect.assert_called_once_with()
        self.assertTrue(self.mock_rados.Rados.return_value.open_ioctx.called)
        self.assertEqual(self.mock_rados.Rados.return_value.ioctx, ret[1])
        self.mock_rados.Rados.return_value.open_ioctx.assert_called_with(
            self.cfg.rbd_pool)

        # different pool
        ret = self.driver._connect_to_rados('alt_pool')
        self.assertTrue(self.mock_rados.Rados.return_value.connect.called)
        self.assertTrue(self.mock_rados.Rados.return_value.open_ioctx.called)
        self.assertEqual(self.mock_rados.Rados.return_value.ioctx, ret[1])
        self.mock_rados.Rados.return_value.open_ioctx.assert_called_with(
            'alt_pool')

        # With timeout
        self.cfg.rados_connect_timeout = 1
        self.mock_rados.Rados.return_value.connect.reset_mock()
        self.driver._connect_to_rados()
        self.mock_rados.Rados.return_value.connect.assert_called_once_with(
            timeout=1)

        # error
        self.mock_rados.Rados.return_value.open_ioctx.reset_mock()
        self.mock_rados.Rados.return_value.shutdown.reset_mock()
        self.mock_rados.Rados.return_value.open_ioctx.side_effect = (
            self.mock_rados.Error)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._connect_to_rados)
        self.assertTrue(self.mock_rados.Rados.return_value.open_ioctx.called)
        self.assertEqual(
            3, self.mock_rados.Rados.return_value.shutdown.call_count)


class RBDImageIOWrapperTestCase(test.TestCase):
    def setUp(self):
        super(RBDImageIOWrapperTestCase, self).setUp()
        self.meta = mock.Mock()
        self.meta.user = 'mock_user'
        self.meta.conf = 'mock_conf'
        self.meta.pool = 'mock_pool'
        self.meta.image = mock.Mock()
        self.meta.image.read = mock.Mock()
        self.meta.image.write = mock.Mock()
        self.meta.image.size = mock.Mock()
        self.mock_rbd_wrapper = driver.RBDImageIOWrapper(self.meta)
        self.data_length = 1024
        self.full_data = b'abcd' * 256

    def test_init(self):
        self.assertEqual(self.mock_rbd_wrapper._rbd_meta, self.meta)
        self.assertEqual(0, self.mock_rbd_wrapper._offset)

    def test_inc_offset(self):
        self.mock_rbd_wrapper._inc_offset(10)
        self.mock_rbd_wrapper._inc_offset(10)
        self.assertEqual(20, self.mock_rbd_wrapper._offset)

    def test_rbd_image(self):
        self.assertEqual(self.mock_rbd_wrapper.rbd_image, self.meta.image)

    def test_rbd_user(self):
        self.assertEqual(self.mock_rbd_wrapper.rbd_user, self.meta.user)

    def test_rbd_pool(self):
        self.assertEqual(self.mock_rbd_wrapper.rbd_conf, self.meta.conf)

    def test_rbd_conf(self):
        self.assertEqual(self.mock_rbd_wrapper.rbd_pool, self.meta.pool)

    def test_read(self):

        def mock_read(offset, length):
            return self.full_data[offset:length]

        self.meta.image.read.side_effect = mock_read
        self.meta.image.size.return_value = self.data_length

        data = self.mock_rbd_wrapper.read()
        self.assertEqual(self.full_data, data)

        data = self.mock_rbd_wrapper.read()
        self.assertEqual(b'', data)

        self.mock_rbd_wrapper.seek(0)
        data = self.mock_rbd_wrapper.read()
        self.assertEqual(self.full_data, data)

        self.mock_rbd_wrapper.seek(0)
        data = self.mock_rbd_wrapper.read(10)
        self.assertEqual(self.full_data[:10], data)

    def test_write(self):
        self.mock_rbd_wrapper.write(self.full_data)
        self.assertEqual(1024, self.mock_rbd_wrapper._offset)

    def test_seekable(self):
        self.assertTrue(self.mock_rbd_wrapper.seekable)

    def test_seek(self):
        self.assertEqual(0, self.mock_rbd_wrapper._offset)
        self.mock_rbd_wrapper.seek(10)
        self.assertEqual(10, self.mock_rbd_wrapper._offset)
        self.mock_rbd_wrapper.seek(10)
        self.assertEqual(10, self.mock_rbd_wrapper._offset)
        self.mock_rbd_wrapper.seek(10, 1)
        self.assertEqual(20, self.mock_rbd_wrapper._offset)

        self.mock_rbd_wrapper.seek(0)
        self.mock_rbd_wrapper.write(self.full_data)
        self.meta.image.size.return_value = self.data_length
        self.mock_rbd_wrapper.seek(0)
        self.assertEqual(0, self.mock_rbd_wrapper._offset)

        self.mock_rbd_wrapper.seek(10, 2)
        self.assertEqual(self.data_length + 10, self.mock_rbd_wrapper._offset)
        self.mock_rbd_wrapper.seek(-10, 2)
        self.assertEqual(self.data_length - 10, self.mock_rbd_wrapper._offset)

        # test exceptions.
        self.assertRaises(IOError, self.mock_rbd_wrapper.seek, 0, 3)
        self.assertRaises(IOError, self.mock_rbd_wrapper.seek, -1)
        # offset should not have been changed by any of the previous
        # operations.
        self.assertEqual(self.data_length - 10, self.mock_rbd_wrapper._offset)

    def test_tell(self):
        self.assertEqual(0, self.mock_rbd_wrapper.tell())
        self.mock_rbd_wrapper._inc_offset(10)
        self.assertEqual(10, self.mock_rbd_wrapper.tell())

    def test_flush(self):
        with mock.patch.object(driver, 'LOG') as mock_logger:
            self.meta.image.flush = mock.Mock()
            self.mock_rbd_wrapper.flush()
            self.meta.image.flush.assert_called_once_with()
            self.meta.image.flush.reset_mock()
            # this should be caught and logged silently.
            self.meta.image.flush.side_effect = AttributeError
            self.mock_rbd_wrapper.flush()
            self.meta.image.flush.assert_called_once_with()
            msg = _("flush() not supported in this version of librbd")
            mock_logger.warning.assert_called_with(msg)

    def test_fileno(self):
        self.assertRaises(IOError, self.mock_rbd_wrapper.fileno)

    def test_close(self):
        self.mock_rbd_wrapper.close()


class ManagedRBDTestCase(test_volume.DriverTestCase):
    driver_name = "cinder.volume.drivers.rbd.RBDDriver"

    def setUp(self):
        super(ManagedRBDTestCase, self).setUp()
        # TODO(dosaboy): need to remove dependency on mox stubs here once
        # image.fake has been converted to mock.
        fake_image.stub_out_image_service(self.stubs)
        self.volume.driver.set_initialized()
        self.volume.stats = {'allocated_capacity_gb': 0,
                             'pools': {}}
        self.called = []

    def _create_volume_from_image(self, expected_status, raw=False,
                                  clone_error=False):
        """Try to clone a volume from an image, and check status afterwards.

        NOTE: if clone_error is True we force the image type to raw otherwise
              clone_image is not called
        """
        volume_id = 1

        # See tests.image.fake for image types.
        if raw:
            image_id = '155d900f-4e14-4e4c-a73d-069cbf4541e6'
        else:
            image_id = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'

        # creating volume testdata
        db.volume_create(self.context,
                         {'id': volume_id,
                          'updated_at': timeutils.utcnow(),
                          'display_description': 'Test Desc',
                          'size': 20,
                          'status': 'creating',
                          'instance_uuid': None,
                          'host': 'dummy'})

        try:
            if not clone_error:
                self.volume.create_volume(self.context,
                                          volume_id,
                                          request_spec={'image_id': image_id})
            else:
                self.assertRaises(exception.CinderException,
                                  self.volume.create_volume,
                                  self.context,
                                  volume_id,
                                  request_spec={'image_id': image_id})

            volume = db.volume_get(self.context, volume_id)
            self.assertEqual(expected_status, volume['status'])
        finally:
            # cleanup
            db.volume_destroy(self.context, volume_id)

    def test_create_vol_from_image_status_available(self):
        """Clone raw image then verify volume is in available state."""

        def _mock_clone_image(context, volume, image_location,
                              image_meta, image_service):
            return {'provider_location': None}, True

        with mock.patch.object(self.volume.driver, 'clone_image') as \
                mock_clone_image:
            mock_clone_image.side_effect = _mock_clone_image
            with mock.patch.object(self.volume.driver, 'create_volume') as \
                    mock_create:
                with mock.patch.object(create_volume.CreateVolumeFromSpecTask,
                                       '_copy_image_to_volume') as mock_copy:
                    self._create_volume_from_image('available', raw=True)
                    self.assertFalse(mock_copy.called)

                self.assertTrue(mock_clone_image.called)
                self.assertFalse(mock_create.called)

    @mock.patch('cinder.image.image_utils.TemporaryImages.fetch')
    def test_create_vol_from_non_raw_image_status_available(self, mock_fetch):
        """Clone non-raw image then verify volume is in available state."""

        def _mock_clone_image(context, volume, image_location,
                              image_meta, image_service):
            return {'provider_location': None}, False

        mock_fetch.return_value = mock.MagicMock(spec=utils.get_file_spec())
        with mock.patch.object(self.volume.driver, 'clone_image') as \
                mock_clone_image:
            mock_clone_image.side_effect = _mock_clone_image
            with mock.patch.object(self.volume.driver, 'create_volume') as \
                    mock_create:
                with mock.patch.object(create_volume.CreateVolumeFromSpecTask,
                                       '_copy_image_to_volume') as mock_copy:
                    self._create_volume_from_image('available', raw=False)
                    self.assertTrue(mock_copy.called)

                self.assertTrue(mock_clone_image.called)
                self.assertTrue(mock_create.called)

    def test_create_vol_from_image_status_error(self):
        """Fail to clone raw image then verify volume is in error state."""
        with mock.patch.object(self.volume.driver, 'clone_image') as \
                mock_clone_image:
            mock_clone_image.side_effect = exception.CinderException
            with mock.patch.object(self.volume.driver, 'create_volume'):
                with mock.patch.object(create_volume.CreateVolumeFromSpecTask,
                                       '_copy_image_to_volume') as mock_copy:
                    self._create_volume_from_image('error', raw=True,
                                                   clone_error=True)
                    self.assertFalse(mock_copy.called)

                self.assertTrue(mock_clone_image.called)
                self.assertFalse(self.volume.driver.create_volume.called)

    def test_clone_failure(self):
        driver = self.volume.driver

        with mock.patch.object(driver, '_is_cloneable', lambda *args: False):
            image_loc = (mock.Mock(), None)
            actual = driver.clone_image(mock.Mock(),
                                        mock.Mock(),
                                        image_loc,
                                        {},
                                        mock.Mock())
            self.assertEqual(({}, False), actual)

        self.assertEqual(({}, False),
                         driver.clone_image('', object(), None, {}, ''))

    def test_clone_success(self):
        expected = ({'provider_location': None}, True)
        driver = self.volume.driver

        with mock.patch.object(self.volume.driver, '_is_cloneable') as \
                mock_is_cloneable:
            mock_is_cloneable.return_value = True
            with mock.patch.object(self.volume.driver, '_clone') as \
                    mock_clone:
                with mock.patch.object(self.volume.driver, '_resize') as \
                        mock_resize:
                    image_loc = ('rbd://fee/fi/fo/fum', None)

                    volume = {'name': 'vol1'}
                    actual = driver.clone_image(mock.Mock(),
                                                volume,
                                                image_loc,
                                                {'disk_format': 'raw',
                                                 'id': 'id.foo'},
                                                mock.Mock())

                    self.assertEqual(expected, actual)
                    mock_clone.assert_called_once_with(volume,
                                                       'fi', 'fo', 'fum')
                    mock_resize.assert_called_once_with(volume)

    def test_clone_multilocation_success(self):
        expected = ({'provider_location': None}, True)
        driver = self.volume.driver

        def cloneable_side_effect(url_location, image_meta):
            return url_location == 'rbd://fee/fi/fo/fum'

        with mock.patch.object(self.volume.driver, '_is_cloneable') \
            as mock_is_cloneable, \
            mock.patch.object(self.volume.driver, '_clone') as mock_clone, \
            mock.patch.object(self.volume.driver, '_resize') \
                as mock_resize:
            mock_is_cloneable.side_effect = cloneable_side_effect
            image_loc = ('rbd://bee/bi/bo/bum',
                         [{'url': 'rbd://bee/bi/bo/bum'},
                          {'url': 'rbd://fee/fi/fo/fum'}])
            volume = {'name': 'vol1'}
            image_meta = mock.sentinel.image_meta
            image_service = mock.sentinel.image_service

            actual = driver.clone_image(self.context,
                                        volume,
                                        image_loc,
                                        image_meta,
                                        image_service)

            self.assertEqual(expected, actual)
            self.assertEqual(2, mock_is_cloneable.call_count)
            mock_clone.assert_called_once_with(volume,
                                               'fi', 'fo', 'fum')
            mock_is_cloneable.assert_called_with('rbd://fee/fi/fo/fum',
                                                 image_meta)
            mock_resize.assert_called_once_with(volume)

    def test_clone_multilocation_failure(self):
        expected = ({}, False)
        driver = self.volume.driver

        with mock.patch.object(driver, '_is_cloneable', return_value=False) \
            as mock_is_cloneable, \
            mock.patch.object(self.volume.driver, '_clone') as mock_clone, \
            mock.patch.object(self.volume.driver, '_resize') \
                as mock_resize:
            image_loc = ('rbd://bee/bi/bo/bum',
                         [{'url': 'rbd://bee/bi/bo/bum'},
                          {'url': 'rbd://fee/fi/fo/fum'}])

            volume = {'name': 'vol1'}
            image_meta = mock.sentinel.image_meta
            image_service = mock.sentinel.image_service
            actual = driver.clone_image(self.context,
                                        volume,
                                        image_loc,
                                        image_meta,
                                        image_service)

            self.assertEqual(expected, actual)
            self.assertEqual(2, mock_is_cloneable.call_count)
            mock_is_cloneable.assert_any_call('rbd://bee/bi/bo/bum',
                                              image_meta)
            mock_is_cloneable.assert_any_call('rbd://fee/fi/fo/fum',
                                              image_meta)
            self.assertFalse(mock_clone.called)
            self.assertFalse(mock_resize.called)
