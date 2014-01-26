
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
from cinder.volume.flows.api import create_volume


LOG = logging.getLogger(__name__)


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
        super(RBDTestCase, self).setUp()

        self.cfg = mock.Mock(spec=conf.Configuration)
        self.cfg.volume_tmp_dir = None
        self.cfg.rbd_pool = 'rbd'
        self.cfg.rbd_ceph_conf = None
        self.cfg.rbd_secret_uuid = None
        self.cfg.rbd_user = None
        self.cfg.volume_dd_blocksize = '1M'

        # set some top level mocks for these common modules and tests can then
        # set method/attributes as required.
        self.rados = mock.Mock()
        self.rbd = mock.Mock()
        self.rbd.RBD = mock.Mock
        self.rbd.Image = mock.Mock
        self.rbd.ImageSnapshot = mock.Mock

        mock_exec = mock.Mock()
        mock_exec.return_value = ('', '')

        self.driver = driver.RBDDriver(execute=mock_exec,
                                       configuration=self.cfg,
                                       rados=self.rados,
                                       rbd=self.rbd)
        self.driver.set_initialized()

        self.volume_name = u'volume-00000001'
        self.snapshot_name = u'snapshot-00000001'
        self.volume_size = 1
        self.volume = dict(name=self.volume_name, size=self.volume_size)
        self.snapshot = dict(volume_name=self.volume_name,
                             name=self.snapshot_name)

    def tearDown(self):
        super(RBDTestCase, self).tearDown()

    @mock.patch('cinder.volume.drivers.rbd.RADOSClient')
    def test_create_volume(self, mock_client):
        client = mock_client.return_value
        client.__enter__.return_value = client

        self.driver._supports_layering = mock.Mock()
        self.driver._supports_layering.return_value = True
        self.rbd.RBD.create = mock.Mock()

        self.driver.create_volume(self.volume)

        args = [client.ioctx, str(self.volume_name),
                self.volume_size * units.GiB]
        kwargs = {'old_format': False,
                  'features': self.rbd.RBD_FEATURE_LAYERING}

        self.rbd.RBD.create.assert_called_once()
        client.__enter__.assert_called_once()
        client.__exit__.assert_called_once()
        self.driver._supports_layering.assert_called_once()
        self.rbd.RBD.create.assert_called_once_with(*args, **kwargs)

    @mock.patch('cinder.volume.drivers.rbd.RADOSClient')
    def test_create_volume_no_layering(self, mock_client):
        client = mock_client.return_value
        client.__enter__.return_value = client

        self.driver._supports_layering = mock.Mock()
        self.driver._supports_layering.return_value = False
        self.rbd.RBD.create = mock.Mock()

        self.driver.create_volume(self.volume)

        args = [client.ioctx, str(self.volume_name),
                self.volume_size * units.GiB]
        kwargs = {'old_format': True,
                  'features': 0}

        self.rbd.RBD.create.assert_called_once()
        client.__enter__.assert_called_once()
        client.__exit__.assert_called_once()
        self.driver._supports_layering.assert_called_once()
        self.rbd.RBD.create.assert_called_once_with(*args, **kwargs)

    @mock.patch('cinder.volume.drivers.rbd.RADOSClient')
    def test_delete_volume(self, mock_client):
        client = mock_client.return_value

        self.driver.rbd.Image.list_snaps = mock.Mock()
        self.driver.rbd.Image.list_snaps.return_value = []
        self.driver.rbd.Image.close = mock.Mock()
        self.driver.rbd.Image.remove = mock.Mock()
        self.driver.rbd.Image.unprotect_snap = mock.Mock()

        self.driver._get_clone_info = mock.Mock()
        self.driver._get_clone_info.return_value = (None, None, None)
        self.driver._delete_backup_snaps = mock.Mock()

        self.driver.delete_volume(self.volume)

        self.driver._get_clone_info.assert_called_once()
        self.driver.rbd.Image.list_snaps.assert_called_once()
        client.__enter__.assert_called_once()
        client.__exit__.assert_called_once()
        self.driver._delete_backup_snaps.assert_called_once()
        self.assertFalse(self.driver.rbd.Image.unprotect_snap.called)
        self.driver.rbd.RBD.remove.assert_called_once()

    @mock.patch('cinder.volume.drivers.rbd.rbd')
    def test_delete_volume_not_found(self, mock_rbd):
        mock_rbd.RBD = mock.Mock
        mock_rbd.ImageNotFound = Exception
        mock_rbd.Image.side_effect = mock_rbd.ImageNotFound

        self.driver.rbd = mock_rbd

        with mock.patch.object(driver, 'RADOSClient'):
            self.assertIsNone(self.driver.delete_volume(self.volume))
            mock_rbd.Image.assert_called_once()

    def test_delete_busy_volume(self):
        self.rbd.Image.close = mock.Mock()
        self.rbd.Image.list_snaps = mock.Mock()
        self.rbd.Image.list_snaps.return_value = []
        self.rbd.Image.unprotect_snap = mock.Mock()

        self.rbd.ImageBusy = Exception
        self.rbd.RBD.remove = mock.Mock()
        self.rbd.RBD.remove.side_effect = self.rbd.ImageBusy

        self.driver._get_clone_info = mock.Mock()
        self.driver._get_clone_info.return_value = (None, None, None)
        self.driver._delete_backup_snaps = mock.Mock()

        with mock.patch.object(driver, 'RADOSClient') as mock_rados_client:
            self.assertRaises(exception.VolumeIsBusy,
                              self.driver.delete_volume, self.volume)

            self.driver._get_clone_info.assert_called_once()
            self.rbd.Image.list_snaps.assert_called_once()
            mock_rados_client.assert_called_once()
            self.driver._delete_backup_snaps.assert_called_once()
            self.assertFalse(self.rbd.Image.unprotect_snap.called)
            self.rbd.RBD.remove.assert_called_once()

    @mock.patch('cinder.volume.drivers.rbd.RBDVolumeProxy')
    def test_create_snapshot(self, mock_proxy):
        proxy = mock_proxy.return_value
        proxy.__enter__.return_value = proxy

        self.driver.create_snapshot(self.snapshot)

        args = [str(self.snapshot_name)]
        proxy.create_snap.assert_called_with(*args)
        proxy.protect_snap.assert_called_with(*args)

    @mock.patch('cinder.volume.drivers.rbd.RBDVolumeProxy')
    def test_delete_snapshot(self, mock_proxy):
        proxy = mock_proxy.return_value
        proxy.__enter__.return_value = proxy

        self.driver.delete_snapshot(self.snapshot)

        args = [str(self.snapshot_name)]
        proxy.remove_snap.assert_called_with(*args)
        proxy.unprotect_snap.assert_called_with(*args)

    def test_get_clone_info(self):

        volume = self.rbd.Image()
        volume.set_snap = mock.Mock()
        volume.parent_info = mock.Mock()
        parent_info = ('a', 'b', '%s.clone_snap' % (self.volume_name))
        volume.parent_info.return_value = parent_info

        info = self.driver._get_clone_info(volume, self.volume_name)

        self.assertEqual(info, parent_info)

        self.assertFalse(volume.set_snap.called)
        volume.parent_info.assert_called_once()

    def test_get_clone_info_w_snap(self):

        volume = self.rbd.Image()
        volume.set_snap = mock.Mock()
        volume.parent_info = mock.Mock()
        parent_info = ('a', 'b', '%s.clone_snap' % (self.volume_name))
        volume.parent_info.return_value = parent_info

        snapshot = self.rbd.ImageSnapshot()

        info = self.driver._get_clone_info(volume, self.volume_name,
                                           snap=snapshot)

        self.assertEqual(info, parent_info)

        volume.set_snap.assert_called_once()
        self.assertEqual(volume.set_snap.call_count, 2)
        volume.parent_info.assert_called_once()

    def test_get_clone_info_w_exception(self):

        self.rbd.ImageNotFound = Exception

        volume = self.rbd.Image()
        volume.set_snap = mock.Mock()
        volume.parent_info = mock.Mock()
        volume.parent_info.side_effect = self.rbd.ImageNotFound

        snapshot = self.rbd.ImageSnapshot()

        info = self.driver._get_clone_info(volume, self.volume_name,
                                           snap=snapshot)

        self.assertEqual(info, (None, None, None))

        volume.set_snap.assert_called_once()
        self.assertEqual(volume.set_snap.call_count, 2)
        volume.parent_info.assert_called_once()

    def test_get_clone_info_deleted_volume(self):

        volume = self.rbd.Image()
        volume.set_snap = mock.Mock()
        volume.parent_info = mock.Mock()
        parent_info = ('a', 'b', '%s.clone_snap' % (self.volume_name))
        volume.parent_info.return_value = parent_info

        info = self.driver._get_clone_info(volume,
                                           "%s.deleted" % (self.volume_name))

        self.assertEqual(info, parent_info)

        self.assertFalse(volume.set_snap.called)
        volume.parent_info.assert_called_once()

    @mock.patch('cinder.volume.drivers.rbd.RADOSClient')
    def test_create_cloned_volume(self, mock_client):
        src_name = u'volume-00000001'
        dst_name = u'volume-00000002'

        self.cfg.rbd_max_clone_depth = 2
        self.rbd.RBD.clone = mock.Mock()
        self.driver._get_clone_depth = mock.Mock()
        # Try with no flatten required
        self.driver._get_clone_depth.return_value = 1

        self.rbd.Image.create_snap = mock.Mock()
        self.rbd.Image.protect_snap = mock.Mock()
        self.rbd.Image.close = mock.Mock()

        self.driver.create_cloned_volume(dict(name=dst_name),
                                         dict(name=src_name))

        self.rbd.Image.create_snap.assert_called_once()
        self.rbd.Image.protect_snap.assert_called_once()
        self.rbd.RBD.clone.assert_called_once()
        self.rbd.Image.close.assert_called_once()

    @mock.patch('cinder.volume.drivers.rbd.RADOSClient')
    def test_create_cloned_volume_w_flatten(self, mock_client):
        src_name = u'volume-00000001'
        dst_name = u'volume-00000002'

        self.cfg.rbd_max_clone_depth = 1
        self.rbd.RBD.Error = Exception
        self.rbd.RBD.clone = mock.Mock()
        self.rbd.RBD.clone.side_effect = self.rbd.RBD.Error
        self.driver._get_clone_depth = mock.Mock()
        # Try with no flatten required
        self.driver._get_clone_depth.return_value = 1

        self.rbd.Image.create_snap = mock.Mock()
        self.rbd.Image.protect_snap = mock.Mock()
        self.rbd.Image.unprotect_snap = mock.Mock()
        self.rbd.Image.remove_snap = mock.Mock()
        self.rbd.Image.close = mock.Mock()

        self.assertRaises(self.rbd.RBD.Error, self.driver.create_cloned_volume,
                          dict(name=dst_name), dict(name=src_name))

        self.rbd.Image.create_snap.assert_called_once()
        self.rbd.Image.protect_snap.assert_called_once()
        self.rbd.RBD.clone.assert_called_once()
        self.rbd.Image.unprotect_snap.assert_called_once()
        self.rbd.Image.remove_snap.assert_called_once()
        self.rbd.Image.close.assert_called_once()

    @mock.patch('cinder.volume.drivers.rbd.RADOSClient')
    def test_create_cloned_volume_w_clone_exception(self, mock_client):
        src_name = u'volume-00000001'
        dst_name = u'volume-00000002'

        self.cfg.rbd_max_clone_depth = 2
        self.rbd.RBD.Error = Exception
        self.rbd.RBD.clone = mock.Mock()
        self.rbd.RBD.clone.side_effect = self.rbd.RBD.Error
        self.driver._get_clone_depth = mock.Mock()
        # Try with no flatten required
        self.driver._get_clone_depth.return_value = 1

        self.rbd.Image.create_snap = mock.Mock()
        self.rbd.Image.protect_snap = mock.Mock()
        self.rbd.Image.unprotect_snap = mock.Mock()
        self.rbd.Image.remove_snap = mock.Mock()
        self.rbd.Image.close = mock.Mock()

        self.assertRaises(self.rbd.RBD.Error, self.driver.create_cloned_volume,
                          dict(name=dst_name), dict(name=src_name))

        self.rbd.Image.create_snap.assert_called_once()
        self.rbd.Image.protect_snap.assert_called_once()
        self.rbd.RBD.clone.assert_called_once()
        self.rbd.Image.unprotect_snap.assert_called_once()
        self.rbd.Image.remove_snap.assert_called_once()
        self.rbd.Image.close.assert_called_once()

    def test_good_locations(self):
        locations = ['rbd://fsid/pool/image/snap',
                     'rbd://%2F/%2F/%2F/%2F', ]
        map(self.driver._parse_location, locations)

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

    @mock.patch('cinder.volume.drivers.rbd.RBDVolumeProxy')
    def test_cloneable(self, mock_proxy):
        self.driver._get_fsid = mock.Mock()
        self.driver._get_fsid.return_value = 'abc'
        location = 'rbd://abc/pool/image/snap'
        info = {'disk_format': 'raw'}
        self.assertTrue(self.driver._is_cloneable(location, info))

    @mock.patch('cinder.volume.drivers.rbd.RBDVolumeProxy')
    def test_uncloneable_different_fsid(self, mock_proxy):
        self.driver._get_fsid = mock.Mock()
        self.driver._get_fsid.return_value = 'abc'
        location = 'rbd://def/pool/image/snap'
        self.assertFalse(
            self.driver._is_cloneable(location, {'disk_format': 'raw'}))

    @mock.patch('cinder.volume.drivers.rbd.RBDVolumeProxy')
    def test_uncloneable_unreadable(self, mock_proxy):
        self.driver._get_fsid = mock.Mock()
        self.driver._get_fsid.return_value = 'abc'
        location = 'rbd://abc/pool/image/snap'

        self.rbd.Error = Exception
        mock_proxy.side_effect = self.rbd.Error

        args = [location, {'disk_format': 'raw'}]
        self.assertFalse(self.driver._is_cloneable(*args))
        mock_proxy.assert_called_once()

    def test_uncloneable_bad_format(self):
        self.driver._get_fsid = mock.Mock()
        self.driver._get_fsid.return_value = 'abc'
        location = 'rbd://abc/pool/image/snap'
        formats = ['qcow2', 'vmdk', 'vdi']
        for f in formats:
            self.assertFalse(
                self.driver._is_cloneable(location, {'disk_format': f}))

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

    def test_copy_image_no_volume_tmp(self):
        self.cfg.volume_tmp_dir = None
        self._copy_image()

    def test_copy_image_volume_tmp(self):
        self.cfg.volume_tmp_dir = '/var/run/cinder/tmp'
        self._copy_image()

    @mock.patch('cinder.volume.drivers.rbd.RADOSClient')
    def test_update_volume_stats(self, mock_client):
        client = mock_client.return_value
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

    @mock.patch('cinder.volume.drivers.rbd.RADOSClient')
    def test_update_volume_stats_error(self, mock_client):
        client = mock_client.return_value
        client.__enter__.return_value = client

        client.cluster = mock.Mock()
        client.cluster.get_cluster_stats = mock.Mock()
        client.cluster.get_cluster_stats.side_effect = Exception

        self.driver.configuration.safe_get = mock.Mock()
        self.driver.configuration.safe_get.return_value = 'RBD'

        self.rados.Error = Exception

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

    def test_get_mon_addrs(self):
        self.driver._execute = mock.Mock()
        self.driver._execute.return_value = (CEPH_MON_DUMP, '')

        hosts = ['::1', '::1', '::1', '127.0.0.1', 'example.com']
        ports = ['6789', '6790', '6791', '6792', '6791']
        self.assertEqual((hosts, ports), self.driver._get_mon_addrs())

    def test_initialize_connection(self):
        hosts = ['::1', '::1', '::1', '127.0.0.1', 'example.com']
        ports = ['6789', '6790', '6791', '6792', '6791']

        self.driver._get_mon_addrs = mock.Mock()
        self.driver._get_mon_addrs.return_value = (hosts, ports)

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
        actual = self.driver.initialize_connection(dict(name=self.volume_name),
                                                   None)
        self.assertDictMatch(expected, actual)

    @mock.patch('cinder.volume.drivers.rbd.RADOSClient')
    def test_clone(self, mock_client):
        src_pool = u'images'
        src_image = u'image-name'
        src_snap = u'snapshot-name'

        client_stack = []

        def mock__enter__(inst):
            def _inner():
                client_stack.append(inst)
                return inst
            return _inner

        client = mock_client.return_value
        # capture both rados client used to perform the clone
        client.__enter__.side_effect = mock__enter__(client)

        self.rbd.RBD.clone = mock.Mock()

        self.driver._clone(self.volume, src_pool, src_image, src_snap)

        args = [client_stack[0].ioctx, str(src_image), str(src_snap),
                client_stack[1].ioctx, str(self.volume_name)]
        kwargs = {'features': self.rbd.RBD_FEATURE_LAYERING}
        self.rbd.RBD.clone.assert_called_once_with(*args, **kwargs)
        self.assertEqual(client.__enter__.call_count, 2)

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

    @mock.patch('cinder.volume.drivers.rbd.RADOSClient')
    def test_rbd_volume_proxy_init(self, mock_client):
        snap = u'snapshot-name'

        client = mock_client.return_value
        client.__enter__.return_value = client

        self.driver._connect_to_rados = mock.Mock()
        self.driver._connect_to_rados.return_value = (None, None)
        self.driver._disconnect_from_rados = mock.Mock()
        self.driver._disconnect_from_rados.return_value = (None, None)

        with driver.RBDVolumeProxy(self.driver, self.volume_name):
            self.driver._connect_to_rados.assert_called_once()
            self.assertFalse(self.driver._disconnect_from_rados.called)

        self.driver._disconnect_from_rados.assert_called_once()

        self.driver._connect_to_rados.reset_mock()
        self.driver._disconnect_from_rados.reset_mock()

        with driver.RBDVolumeProxy(self.driver, self.volume_name,
                                   snapshot=snap):
            self.driver._connect_to_rados.assert_called_once()
            self.assertFalse(self.driver._disconnect_from_rados.called)

        self.driver._disconnect_from_rados.assert_called_once()

    @mock.patch('cinder.volume.drivers.rbd.RADOSClient')
    def test_connect_to_rados(self, mock_client):
        client = mock_client.return_value
        client.__enter__.return_value = client
        client.open_ioctx = mock.Mock()

        mock_ioctx = mock.Mock()
        client.open_ioctx.return_value = mock_ioctx

        self.rados.Error = test.TestingException
        self.rados.Rados.return_value = client

        # default configured pool
        self.assertEqual((client, mock_ioctx),
                         self.driver._connect_to_rados())
        client.open_ioctx.assert_called_with(self.cfg.rbd_pool)

        # different pool
        self.assertEqual((client, mock_ioctx),
                         self.driver._connect_to_rados('images'))
        client.open_ioctx.assert_called_with('images')

        # error
        client.open_ioctx.reset_mock()
        client.shutdown.reset_mock()
        client.open_ioctx.side_effect = self.rados.Error
        self.assertRaises(test.TestingException, self.driver._connect_to_rados)
        client.open_ioctx.assert_called_once()
        client.shutdown.assert_called_once()


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
        self.rbd_wrapper = driver.RBDImageIOWrapper(self.meta)
        self.data_length = 1024
        self.full_data = 'abcd' * 256

    def tearDown(self):
        super(RBDImageIOWrapperTestCase, self).tearDown()

    def test_init(self):
        self.assertEqual(self.rbd_wrapper._rbd_meta, self.meta)
        self.assertEqual(self.rbd_wrapper._offset, 0)

    def test_inc_offset(self):
        self.rbd_wrapper._inc_offset(10)
        self.rbd_wrapper._inc_offset(10)
        self.assertEqual(self.rbd_wrapper._offset, 20)

    def test_rbd_image(self):
        self.assertEqual(self.rbd_wrapper.rbd_image, self.meta.image)

    def test_rbd_user(self):
        self.assertEqual(self.rbd_wrapper.rbd_user, self.meta.user)

    def test_rbd_pool(self):
        self.assertEqual(self.rbd_wrapper.rbd_conf, self.meta.conf)

    def test_rbd_conf(self):
        self.assertEqual(self.rbd_wrapper.rbd_pool, self.meta.pool)

    def test_read(self):

        def mock_read(offset, length):
            return self.full_data[offset:length]

        self.meta.image.read.side_effect = mock_read
        self.meta.image.size.return_value = self.data_length

        data = self.rbd_wrapper.read()
        self.assertEqual(data, self.full_data)

        data = self.rbd_wrapper.read()
        self.assertEqual(data, '')

        self.rbd_wrapper.seek(0)
        data = self.rbd_wrapper.read()
        self.assertEqual(data, self.full_data)

        self.rbd_wrapper.seek(0)
        data = self.rbd_wrapper.read(10)
        self.assertEqual(data, self.full_data[:10])

    def test_write(self):
        self.rbd_wrapper.write(self.full_data)
        self.assertEqual(self.rbd_wrapper._offset, 1024)

    def test_seekable(self):
        self.assertTrue(self.rbd_wrapper.seekable)

    def test_seek(self):
        self.assertEqual(self.rbd_wrapper._offset, 0)
        self.rbd_wrapper.seek(10)
        self.assertEqual(self.rbd_wrapper._offset, 10)
        self.rbd_wrapper.seek(10)
        self.assertEqual(self.rbd_wrapper._offset, 10)
        self.rbd_wrapper.seek(10, 1)
        self.assertEqual(self.rbd_wrapper._offset, 20)

        self.rbd_wrapper.seek(0)
        self.rbd_wrapper.write(self.full_data)
        self.meta.image.size.return_value = self.data_length
        self.rbd_wrapper.seek(0)
        self.assertEqual(self.rbd_wrapper._offset, 0)

        self.rbd_wrapper.seek(10, 2)
        self.assertEqual(self.rbd_wrapper._offset, self.data_length + 10)
        self.rbd_wrapper.seek(-10, 2)
        self.assertEqual(self.rbd_wrapper._offset, self.data_length - 10)

        # test exceptions.
        self.assertRaises(IOError, self.rbd_wrapper.seek, 0, 3)
        self.assertRaises(IOError, self.rbd_wrapper.seek, -1)
        # offset should not have been changed by any of the previous
        # operations.
        self.assertEqual(self.rbd_wrapper._offset, self.data_length - 10)

    def test_tell(self):
        self.assertEqual(self.rbd_wrapper.tell(), 0)
        self.rbd_wrapper._inc_offset(10)
        self.assertEqual(self.rbd_wrapper.tell(), 10)

    def test_flush(self):
        with mock.patch.object(driver, 'LOG') as mock_logger:
            self.meta.image.flush = mock.Mock()
            self.rbd_wrapper.flush()
            self.meta.image.flush.assert_called_once()
            self.meta.image.flush.reset_mock()
            # this should be caught and logged silently.
            self.meta.image.flush.side_effect = AttributeError
            self.rbd_wrapper.flush()
            self.meta.image.flush.assert_called_once()
            msg = _("flush() not supported in this version of librbd")
            mock_logger.warning.assert_called_with(msg)

    def test_fileno(self):
        self.assertRaises(IOError, self.rbd_wrapper.fileno)

    def test_close(self):
        self.rbd_wrapper.close()


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

        def mock_clone_image(volume, image_location, image_id, image_meta):
            return {'provider_location': None}, True

        self.volume.driver.clone_image = mock.Mock()
        self.volume.driver.clone_image.side_effect = mock_clone_image
        self.volume.driver.create_volume = mock.Mock()

        with mock.patch.object(create_volume.CreateVolumeFromSpecTask,
                               '_copy_image_to_volume') as mock_copy:
            self._create_volume_from_image('available', raw=True)

        self.volume.driver.clone_image.assert_called_once()
        self.assertFalse(self.volume.driver.create_volume.called)
        self.assertFalse(mock_copy.called)

    def test_create_vol_from_non_raw_image_status_available(self):
        """Clone non-raw image then verify volume is in available state."""

        def mock_clone_image(volume, image_location, image_id, image_meta):
            return {'provider_location': None}, False

        self.volume.driver.clone_image = mock.Mock()
        self.volume.driver.clone_image.side_effect = mock_clone_image
        self.volume.driver.create_volume = mock.Mock()
        self.volume.driver.create_volume.return_value = None

        with mock.patch.object(create_volume.CreateVolumeFromSpecTask,
                               '_copy_image_to_volume') as mock_copy:
            self._create_volume_from_image('available', raw=False)

        self.volume.driver.clone_image.assert_called_once()
        self.volume.driver.create_volume.assert_called_once()
        mock_copy.assert_called_once()

    def test_create_vol_from_image_status_error(self):
        """Fail to clone raw image then verify volume is in error state."""

        self.volume.driver.clone_image = mock.Mock()
        self.volume.driver.clone_image.side_effect = exception.CinderException
        self.volume.driver.create_volume = mock.Mock()
        self.volume.driver.create_volume.return_value = None

        with mock.patch.object(create_volume.CreateVolumeFromSpecTask,
                               '_copy_image_to_volume') as mock_copy:
            self._create_volume_from_image('error', raw=True, clone_error=True)

        self.volume.driver.clone_image.assert_called_once()
        self.assertFalse(self.volume.driver.create_volume.called)
        self.assertFalse(mock_copy.called)

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

        self.volume.driver._is_cloneable = mock.Mock()
        self.volume.driver._is_cloneable.return_value = True
        self.volume.driver._clone = mock.Mock()
        self.volume.driver._resize = mock.Mock()

        image_loc = ('rbd://fee/fi/fo/fum', None)
        actual = driver.clone_image({'name': 'vol1'},
                                    image_loc,
                                    'id.foo',
                                    {'disk_format': 'raw'})

        self.assertEqual(expected, actual)
        self.volume.driver._clone.assert_called_once()
        self.volume.driver._resize.assert_called_once()
