
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


import mock
import os
import tempfile

from cinder import db
from cinder import exception
from cinder.image import image_utils
from cinder.openstack.common import log as logging
from cinder.openstack.common import timeutils
from cinder import test
from cinder.tests.image import fake as fake_image
from cinder.tests.test_volume import DriverTestCase
from cinder import units
from cinder.volume import configuration as conf
import cinder.volume.drivers.rbd as driver
from cinder.volume.flows.manager import create_volume


LOG = logging.getLogger(__name__)


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


def common_mocks(f):
    """Decorator to set mocks common to all tests.

    The point of doing these mocks here is so that we don't accidentally set
    mocks that can't/dont't get unset.
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
            inst.mock_rados.Rados = mock.Mock
            inst.mock_rados.Rados.ioctx = mock.Mock()
            inst.mock_rbd.RBD = mock.Mock
            inst.mock_rbd.Image = mock.Mock
            inst.mock_rbd.Image.close = mock.Mock()
            inst.mock_rbd.RBD.Error = Exception
            inst.mock_rados.Error = Exception
            inst.mock_rbd.ImageBusy = MockImageBusyException
            inst.mock_rbd.ImageNotFound = MockImageNotFoundException

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


class TestUtil(test.TestCase):
    def test_ascii_str(self):
        self.assertIsNone(driver.ascii_str(None))
        self.assertEqual('foo', driver.ascii_str('foo'))
        self.assertEqual('foo', driver.ascii_str(u'foo'))
        self.assertRaises(UnicodeEncodeError,
                          driver.ascii_str, 'foo' + unichr(300))


class RBDTestCase(test.TestCase):

    def setUp(self):
        global RAISED_EXCEPTIONS
        RAISED_EXCEPTIONS = []
        super(RBDTestCase, self).setUp()

        self.cfg = mock.Mock(spec=conf.Configuration)
        self.cfg.volume_tmp_dir = None
        self.cfg.rbd_pool = 'rbd'
        self.cfg.rbd_ceph_conf = None
        self.cfg.rbd_secret_uuid = None
        self.cfg.rbd_user = None
        self.cfg.volume_dd_blocksize = '1M'

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

    def tearDown(self):
        super(RBDTestCase, self).tearDown()

    @common_mocks
    def test_create_volume(self):
        client = self.mock_client.return_value
        client.__enter__.return_value = client

        with mock.patch.object(self.driver, '_supports_layering') as \
                mock_supports_layering:
            mock_supports_layering.return_value = True
            self.mock_rbd.RBD.create = mock.Mock()

            self.driver.create_volume(self.volume)

            args = [client.ioctx, str(self.volume_name),
                    self.volume_size * units.GiB]
            kwargs = {'old_format': False,
                      'features': self.mock_rbd.RBD_FEATURE_LAYERING}
            self.mock_rbd.RBD.create.assert_called_once_with(*args, **kwargs)
            client.__enter__.assert_called_once()
            client.__exit__.assert_called_once()
            mock_supports_layering.assert_called_once()

    @common_mocks
    def test_create_volume_no_layering(self):
        client = self.mock_client.return_value
        client.__enter__.return_value = client

        with mock.patch.object(self.driver, '_supports_layering') as \
                mock_supports_layering:
            mock_supports_layering.return_value = False
            self.mock_rbd.RBD.create = mock.Mock()

            self.driver.create_volume(self.volume)

            args = [client.ioctx, str(self.volume_name),
                    self.volume_size * units.GiB]
            kwargs = {'old_format': True,
                      'features': 0}
            self.mock_rbd.RBD.create.assert_called_once_with(*args, **kwargs)
            client.__enter__.assert_called_once()
            client.__exit__.assert_called_once()
            mock_supports_layering.assert_called_once()

    @common_mocks
    def test_delete_volume(self):
        client = self.mock_client.return_value

        self.driver.rbd.Image.list_snaps = mock.Mock()
        self.driver.rbd.Image.list_snaps.return_value = []
        self.driver.rbd.Image.close = mock.Mock()
        self.driver.rbd.Image.remove = mock.Mock()
        self.driver.rbd.Image.unprotect_snap = mock.Mock()

        with mock.patch.object(self.driver, '_get_clone_info') as \
                mock_get_clone_info:
            with mock.patch.object(self.driver, '_delete_backup_snaps') as \
                    mock_delete_backup_snaps:
                mock_get_clone_info.return_value = (None, None, None)

                self.driver.delete_volume(self.volume)

                mock_get_clone_info.assert_called_once()
                self.driver.rbd.Image.list_snaps.assert_called_once()
                client.__enter__.assert_called_once()
                client.__exit__.assert_called_once()
                mock_delete_backup_snaps.assert_called_once()
                self.assertFalse(self.driver.rbd.Image.unprotect_snap.called)
                self.driver.rbd.RBD.remove.assert_called_once()

    @common_mocks
    def delete_volume_not_found(self):
        self.mock_rbd.Image.side_effect = self.mock_rbd.ImageNotFound
        self.assertIsNone(self.driver.delete_volume(self.volume))
        self.mock_rbd.Image.assert_called_once()
        # Make sure the exception was raised
        self.assertEqual(RAISED_EXCEPTIONS, [self.mock_rbd.ImageNotFound])

    @common_mocks
    def test_delete_busy_volume(self):
        self.mock_rbd.Image.list_snaps = mock.Mock()
        self.mock_rbd.Image.list_snaps.return_value = []
        self.mock_rbd.Image.unprotect_snap = mock.Mock()

        self.mock_rbd.RBD.remove = mock.Mock()
        self.mock_rbd.RBD.remove.side_effect = self.mock_rbd.ImageBusy

        with mock.patch.object(self.driver, '_get_clone_info') as \
                mock_get_clone_info:
            mock_get_clone_info.return_value = (None, None, None)
            with mock.patch.object(self.driver, '_delete_backup_snaps') as \
                    mock_delete_backup_snaps:
                with mock.patch.object(driver, 'RADOSClient') as \
                        mock_rados_client:
                    self.assertRaises(exception.VolumeIsBusy,
                                      self.driver.delete_volume, self.volume)

                    mock_get_clone_info.assert_called_once()
                    self.mock_rbd.Image.list_snaps.assert_called_once()
                    mock_rados_client.assert_called_once()
                    mock_delete_backup_snaps.assert_called_once()
                    self.assertFalse(self.mock_rbd.Image.unprotect_snap.called)
                    self.mock_rbd.RBD.remove.assert_called_once()
                    # Make sure the exception was raised
                    self.assertEqual(RAISED_EXCEPTIONS,
                                     [self.mock_rbd.ImageBusy])

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

        args = [str(self.snapshot_name)]
        proxy.remove_snap.assert_called_with(*args)
        proxy.unprotect_snap.assert_called_with(*args)

    @common_mocks
    def test_get_clone_info(self):
        volume = self.mock_rbd.Image()
        volume.set_snap = mock.Mock()
        volume.parent_info = mock.Mock()
        parent_info = ('a', 'b', '%s.clone_snap' % (self.volume_name))
        volume.parent_info.return_value = parent_info

        info = self.driver._get_clone_info(volume, self.volume_name)

        self.assertEqual(info, parent_info)

        self.assertFalse(volume.set_snap.called)
        volume.parent_info.assert_called_once()

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

        self.assertEqual(info, parent_info)

        volume.set_snap.assert_called_once()
        self.assertEqual(volume.set_snap.call_count, 2)
        volume.parent_info.assert_called_once()

    @common_mocks
    def test_get_clone_info_w_exception(self):
        volume = self.mock_rbd.Image()
        volume.set_snap = mock.Mock()
        volume.parent_info = mock.Mock()
        volume.parent_info.side_effect = self.mock_rbd.ImageNotFound

        snapshot = self.mock_rbd.ImageSnapshot()

        info = self.driver._get_clone_info(volume, self.volume_name,
                                           snap=snapshot)

        self.assertEqual(info, (None, None, None))

        volume.set_snap.assert_called_once()
        self.assertEqual(volume.set_snap.call_count, 2)
        volume.parent_info.assert_called_once()
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

        self.assertEqual(info, parent_info)

        self.assertFalse(volume.set_snap.called)
        volume.parent_info.assert_called_once()

    @common_mocks
    def test_create_cloned_volume(self):
        src_name = u'volume-00000001'
        dst_name = u'volume-00000002'

        self.cfg.rbd_max_clone_depth = 2
        self.mock_rbd.RBD.clone = mock.Mock()

        with mock.patch.object(self.driver, '_get_clone_depth') as \
                mock_get_clone_depth:
            # Try with no flatten required
            mock_get_clone_depth.return_value = 1

            self.mock_rbd.Image.create_snap = mock.Mock()
            self.mock_rbd.Image.protect_snap = mock.Mock()
            self.mock_rbd.Image.close = mock.Mock()

            self.driver.create_cloned_volume(dict(name=dst_name),
                                             dict(name=src_name))

            self.mock_rbd.Image.create_snap.assert_called_once()
            self.mock_rbd.Image.protect_snap.assert_called_once()
            self.mock_rbd.RBD.clone.assert_called_once()
            self.mock_rbd.Image.close.assert_called_once()
            self.assertTrue(mock_get_clone_depth.called)

    @common_mocks
    def test_create_cloned_volume_w_flatten(self):
        src_name = u'volume-00000001'
        dst_name = u'volume-00000002'

        self.cfg.rbd_max_clone_depth = 1
        self.mock_rbd.RBD.clone = mock.Mock()
        self.mock_rbd.RBD.clone.side_effect = self.mock_rbd.RBD.Error

        with mock.patch.object(self.driver, '_get_clone_depth') as \
                mock_get_clone_depth:
            # Try with no flatten required
            mock_get_clone_depth.return_value = 1

            self.mock_rbd.Image.create_snap = mock.Mock()
            self.mock_rbd.Image.protect_snap = mock.Mock()
            self.mock_rbd.Image.unprotect_snap = mock.Mock()
            self.mock_rbd.Image.remove_snap = mock.Mock()
            self.mock_rbd.Image.close = mock.Mock()

            self.assertRaises(self.mock_rbd.RBD.Error,
                              self.driver.create_cloned_volume,
                              dict(name=dst_name), dict(name=src_name))

            self.mock_rbd.Image.create_snap.assert_called_once()
            self.mock_rbd.Image.protect_snap.assert_called_once()
            self.mock_rbd.RBD.clone.assert_called_once()
            self.mock_rbd.Image.unprotect_snap.assert_called_once()
            self.mock_rbd.Image.remove_snap.assert_called_once()
            self.mock_rbd.Image.close.assert_called_once()
            self.assertTrue(mock_get_clone_depth.called)

    @common_mocks
    def test_create_cloned_volume_w_clone_exception(self):
        src_name = u'volume-00000001'
        dst_name = u'volume-00000002'

        self.cfg.rbd_max_clone_depth = 2
        self.mock_rbd.RBD.clone = mock.Mock()
        self.mock_rbd.RBD.clone.side_effect = self.mock_rbd.RBD.Error
        with mock.patch.object(self.driver, '_get_clone_depth') as \
                mock_get_clone_depth:
            # Try with no flatten required
            mock_get_clone_depth.return_value = 1

            self.mock_rbd.Image.create_snap = mock.Mock()
            self.mock_rbd.Image.protect_snap = mock.Mock()
            self.mock_rbd.Image.unprotect_snap = mock.Mock()
            self.mock_rbd.Image.remove_snap = mock.Mock()
            self.mock_rbd.Image.close = mock.Mock()

            self.assertRaises(self.mock_rbd.RBD.Error,
                              self.driver.create_cloned_volume,
                              dict(name=dst_name), dict(name=src_name))

            self.mock_rbd.Image.create_snap.assert_called_once()
            self.mock_rbd.Image.protect_snap.assert_called_once()
            self.mock_rbd.RBD.clone.assert_called_once()
            self.mock_rbd.Image.unprotect_snap.assert_called_once()
            self.mock_rbd.Image.remove_snap.assert_called_once()
            self.mock_rbd.Image.close.assert_called_once()

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

            self.mock_proxy.side_effect = self.mock_rbd.Error

            args = [location, {'disk_format': 'raw'}]
            self.assertFalse(self.driver._is_cloneable(*args))
            self.mock_proxy.assert_called_once()
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
        self._copy_image()

    @common_mocks
    def test_copy_image_volume_tmp(self):
        self.cfg.volume_tmp_dir = '/var/run/cinder/tmp'
        self._copy_image()

    @common_mocks
    def test_update_volume_stats(self):
        client = self.mock_client.return_value
        client.__enter__.return_value = client

        client.cluster = mock.Mock()
        client.cluster.get_cluster_stats = mock.Mock()
        client.cluster.get_cluster_stats.return_value = {'kb': 1024 ** 3,
                                                         'kb_avail': 1024 ** 2}

        self.driver.configuration.safe_get = mock.Mock()
        self.driver.configuration.safe_get.return_value = 'RBD'

        expected = dict(
            volume_backend_name='RBD',
            vendor_name='Open Source',
            driver_version=self.driver.VERSION,
            storage_protocol='ceph',
            total_capacity_gb=1024,
            free_capacity_gb=1,
            reserved_percentage=0)

        actual = self.driver.get_volume_stats(True)
        client.cluster.get_cluster_stats.assert_called_once()
        self.assertDictMatch(expected, actual)

    @common_mocks
    def test_update_volume_stats_error(self):
        client = self.mock_client.return_value
        client.__enter__.return_value = client

        client.cluster = mock.Mock()
        client.cluster.get_cluster_stats = mock.Mock()
        client.cluster.get_cluster_stats.side_effect = Exception

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
        client.cluster.get_cluster_stats.assert_called_once()
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
                    'secret_uuid': None, }
            }
            volume = dict(name=self.volume_name)
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

        self.mock_rbd.RBD.clone = mock.Mock()

        self.driver._clone(self.volume, src_pool, src_image, src_snap)

        args = [client_stack[0].ioctx, str(src_image), str(src_snap),
                client_stack[1].ioctx, str(self.volume_name)]
        kwargs = {'features': self.mock_rbd.RBD_FEATURE_LAYERING}
        self.mock_rbd.RBD.clone.assert_called_once_with(*args, **kwargs)
        self.assertEqual(client.__enter__.call_count, 2)

    @common_mocks
    def test_extend_volume(self):
        fake_size = '20'
        fake_vol = {'project_id': 'testprjid', 'name': self.volume_name,
                    'size': fake_size,
                    'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66'}

        self.mox.StubOutWithMock(self.driver, '_resize')
        size = int(fake_size) * units.GiB
        self.driver._resize(fake_vol, size=size)

        self.mox.ReplayAll()
        self.driver.extend_volume(fake_vol, fake_size)

        self.mox.VerifyAll()

    @common_mocks
    def test_rbd_volume_proxy_init(self):
        snap = u'snapshot-name'

        client = self.mock_client.return_value
        client.__enter__.return_value = client

        with mock.patch.object(self.driver, '_connect_to_rados') as \
                mock_connect_from_rados:
            with mock.patch.object(self.driver, '_disconnect_from_rados') as \
                    mock_disconnect_from_rados:
                mock_connect_from_rados.return_value = (None, None)
                mock_disconnect_from_rados.return_value = (None, None)

                with driver.RBDVolumeProxy(self.driver, self.volume_name):
                    mock_connect_from_rados.assert_called_once()
                    self.assertFalse(mock_disconnect_from_rados.called)

                mock_disconnect_from_rados.assert_called_once()

                mock_connect_from_rados.reset_mock()
                mock_disconnect_from_rados.reset_mock()

                with driver.RBDVolumeProxy(self.driver, self.volume_name,
                                           snapshot=snap):
                    mock_connect_from_rados.assert_called_once()
                    self.assertFalse(mock_disconnect_from_rados.called)

                mock_disconnect_from_rados.assert_called_once()

    @common_mocks
    def test_connect_to_rados(self):
        self.mock_rados.Rados.connect = mock.Mock()
        self.mock_rados.Rados.shutdown = mock.Mock()
        self.mock_rados.Rados.open_ioctx = mock.Mock()
        self.mock_rados.Rados.open_ioctx.return_value = \
            self.mock_rados.Rados.ioctx

        # default configured pool
        ret = self.driver._connect_to_rados()
        self.assertTrue(self.mock_rados.Rados.connect.called)
        self.assertTrue(self.mock_rados.Rados.open_ioctx.called)
        self.assertIsInstance(ret[0], self.mock_rados.Rados)
        self.assertEqual(ret[1], self.mock_rados.Rados.ioctx)
        self.mock_rados.Rados.open_ioctx.assert_called_with(self.cfg.rbd_pool)

        # different pool
        ret = self.driver._connect_to_rados('alt_pool')
        self.assertTrue(self.mock_rados.Rados.connect.called)
        self.assertTrue(self.mock_rados.Rados.open_ioctx.called)
        self.assertIsInstance(ret[0], self.mock_rados.Rados)
        self.assertEqual(ret[1], self.mock_rados.Rados.ioctx)
        self.mock_rados.Rados.open_ioctx.assert_called_with('alt_pool')

        # error
        self.mock_rados.Rados.open_ioctx.reset_mock()
        self.mock_rados.Rados.shutdown.reset_mock()
        self.mock_rados.Rados.open_ioctx.side_effect = self.mock_rados.Error
        self.assertRaises(self.mock_rados.Error, self.driver._connect_to_rados)
        self.mock_rados.Rados.open_ioctx.assert_called_once()
        self.mock_rados.Rados.shutdown.assert_called_once()


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
        self.full_data = 'abcd' * 256

    def tearDown(self):
        super(RBDImageIOWrapperTestCase, self).tearDown()

    def test_init(self):
        self.assertEqual(self.mock_rbd_wrapper._rbd_meta, self.meta)
        self.assertEqual(self.mock_rbd_wrapper._offset, 0)

    def test_inc_offset(self):
        self.mock_rbd_wrapper._inc_offset(10)
        self.mock_rbd_wrapper._inc_offset(10)
        self.assertEqual(self.mock_rbd_wrapper._offset, 20)

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
        self.assertEqual(data, self.full_data)

        data = self.mock_rbd_wrapper.read()
        self.assertEqual(data, '')

        self.mock_rbd_wrapper.seek(0)
        data = self.mock_rbd_wrapper.read()
        self.assertEqual(data, self.full_data)

        self.mock_rbd_wrapper.seek(0)
        data = self.mock_rbd_wrapper.read(10)
        self.assertEqual(data, self.full_data[:10])

    def test_write(self):
        self.mock_rbd_wrapper.write(self.full_data)
        self.assertEqual(self.mock_rbd_wrapper._offset, 1024)

    def test_seekable(self):
        self.assertTrue(self.mock_rbd_wrapper.seekable)

    def test_seek(self):
        self.assertEqual(self.mock_rbd_wrapper._offset, 0)
        self.mock_rbd_wrapper.seek(10)
        self.assertEqual(self.mock_rbd_wrapper._offset, 10)
        self.mock_rbd_wrapper.seek(10)
        self.assertEqual(self.mock_rbd_wrapper._offset, 10)
        self.mock_rbd_wrapper.seek(10, 1)
        self.assertEqual(self.mock_rbd_wrapper._offset, 20)

        self.mock_rbd_wrapper.seek(0)
        self.mock_rbd_wrapper.write(self.full_data)
        self.meta.image.size.return_value = self.data_length
        self.mock_rbd_wrapper.seek(0)
        self.assertEqual(self.mock_rbd_wrapper._offset, 0)

        self.mock_rbd_wrapper.seek(10, 2)
        self.assertEqual(self.mock_rbd_wrapper._offset, self.data_length + 10)
        self.mock_rbd_wrapper.seek(-10, 2)
        self.assertEqual(self.mock_rbd_wrapper._offset, self.data_length - 10)

        # test exceptions.
        self.assertRaises(IOError, self.mock_rbd_wrapper.seek, 0, 3)
        self.assertRaises(IOError, self.mock_rbd_wrapper.seek, -1)
        # offset should not have been changed by any of the previous
        # operations.
        self.assertEqual(self.mock_rbd_wrapper._offset, self.data_length - 10)

    def test_tell(self):
        self.assertEqual(self.mock_rbd_wrapper.tell(), 0)
        self.mock_rbd_wrapper._inc_offset(10)
        self.assertEqual(self.mock_rbd_wrapper.tell(), 10)

    def test_flush(self):
        with mock.patch.object(driver, 'LOG') as mock_logger:
            self.meta.image.flush = mock.Mock()
            self.mock_rbd_wrapper.flush()
            self.meta.image.flush.assert_called_once()
            self.meta.image.flush.reset_mock()
            # this should be caught and logged silently.
            self.meta.image.flush.side_effect = AttributeError
            self.mock_rbd_wrapper.flush()
            self.meta.image.flush.assert_called_once()
            msg = _("flush() not supported in this version of librbd")
            mock_logger.warning.assert_called_with(msg)

    def test_fileno(self):
        self.assertRaises(IOError, self.mock_rbd_wrapper.fileno)

    def test_close(self):
        self.mock_rbd_wrapper.close()


class ManagedRBDTestCase(DriverTestCase):
    driver_name = "cinder.volume.drivers.rbd.RBDDriver"

    def setUp(self):
        super(ManagedRBDTestCase, self).setUp()
        # TODO(dosaboy): need to remove dependency on mox stubs here once
        # image.fake has been converted to mock.
        fake_image.stub_out_image_service(self.stubs)
        self.volume.driver.set_initialized()
        self.volume.stats = {'allocated_capacity_gb': 0}
        self.called = []

    def _create_volume_from_image(self, expected_status, raw=False,
                                  clone_error=False):
        """Try to clone a volume from an image, and check the status
        afterwards.

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
                                          image_id=image_id)
            else:
                self.assertRaises(exception.CinderException,
                                  self.volume.create_volume,
                                  self.context,
                                  volume_id,
                                  image_id=image_id)

            volume = db.volume_get(self.context, volume_id)
            self.assertEqual(volume['status'], expected_status)
        finally:
            # cleanup
            db.volume_destroy(self.context, volume_id)

    def test_create_vol_from_image_status_available(self):
        """Clone raw image then verify volume is in available state."""

        def _mock_clone_image(volume, image_location, image_id, image_meta):
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

                mock_clone_image.assert_called_once()
                self.assertFalse(mock_create.called)

    def test_create_vol_from_non_raw_image_status_available(self):
        """Clone non-raw image then verify volume is in available state."""

        def _mock_clone_image(volume, image_location, image_id, image_meta):
            return {'provider_location': None}, False

        with mock.patch.object(self.volume.driver, 'clone_image') as \
                mock_clone_image:
            mock_clone_image.side_effect = _mock_clone_image
            with mock.patch.object(self.volume.driver, 'create_volume') as \
                    mock_create:
                with mock.patch.object(create_volume.CreateVolumeFromSpecTask,
                                       '_copy_image_to_volume') as mock_copy:
                    self._create_volume_from_image('available', raw=False)
                    mock_copy.assert_called_once()

                mock_clone_image.assert_called_once()
                mock_create.assert_called_once()

    def test_create_vol_from_image_status_error(self):
        """Fail to clone raw image then verify volume is in error state."""
        with mock.patch.object(self.volume.driver, 'clone_image') as \
                mock_clone_image:
            mock_clone_image.side_effect = exception.CinderException
            with mock.patch.object(self.volume.driver, 'create_volume') as \
                    mock_create:
                with mock.patch.object(create_volume.CreateVolumeFromSpecTask,
                                       '_copy_image_to_volume') as mock_copy:
                    self._create_volume_from_image('error', raw=True,
                                                   clone_error=True)
                    self.assertFalse(mock_copy.called)

                mock_clone_image.assert_called_once()
                self.assertFalse(self.volume.driver.create_volume.called)

    def test_clone_failure(self):
        driver = self.volume.driver

        with mock.patch.object(driver, '_is_cloneable', lambda *args: False):
            image_loc = (mock.Mock(), mock.Mock())
            actual = driver.clone_image(mock.Mock(), image_loc,
                                        mock.Mock(), {})
            self.assertEqual(({}, False), actual)

        self.assertEqual(({}, False),
                         driver.clone_image(object(), None, None, {}))

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

                    actual = driver.clone_image({'name': 'vol1'}, image_loc,
                                                'id.foo',
                                                {'disk_format': 'raw'})

                    self.assertEqual(expected, actual)
                    mock_clone.assert_called_once()
                    mock_resize.assert_called_once()
