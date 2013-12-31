
# Copyright 2012 Josh Durgin
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


import contextlib
import mock
import mox
import os
import tempfile

from cinder import db
from cinder import exception
from cinder.image import image_utils
from cinder.openstack.common import log as logging
from cinder.openstack.common import timeutils
from cinder import test
from cinder.tests.backup.fake_rados import mock_rados
from cinder.tests.backup.fake_rados import mock_rbd
from cinder.tests.image import fake as fake_image
from cinder.tests.test_volume import DriverTestCase
from cinder import units
from cinder.volume import configuration as conf
import cinder.volume.drivers.rbd as driver
from cinder.volume.flows import create_volume


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


class FakeImageService:
    def download(self, context, image_id, path):
        pass


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

        def fake_execute(*args, **kwargs):
            return '', ''
        self.configuration = mox.MockObject(conf.Configuration)
        self.configuration.volume_tmp_dir = None
        self.configuration.rbd_pool = 'rbd'
        self.configuration.rbd_ceph_conf = None
        self.configuration.rbd_secret_uuid = None
        self.configuration.rbd_user = None
        self.configuration.append_config_values(mox.IgnoreArg())
        self.configuration.volume_dd_blocksize = '1M'

        self.rados = self.mox.CreateMockAnything()
        self.rbd = self.mox.CreateMockAnything()
        self.driver = driver.RBDDriver(execute=fake_execute,
                                       configuration=self.configuration,
                                       rados=self.rados,
                                       rbd=self.rbd)
        self.driver.set_initialized()

    def tearDown(self):
        super(RBDTestCase, self).tearDown()

    def test_create_volume(self):
        name = u'volume-00000001'
        size = 1
        volume = dict(name=name, size=size)
        mock_client = self.mox.CreateMockAnything()
        self.mox.StubOutWithMock(driver, 'RADOSClient')

        driver.RADOSClient(self.driver).AndReturn(mock_client)
        mock_client.__enter__().AndReturn(mock_client)
        self.rbd.RBD_FEATURE_LAYERING = 1
        _mock_rbd = self.mox.CreateMockAnything()
        self.rbd.RBD().AndReturn(_mock_rbd)
        _mock_rbd.create(mox.IgnoreArg(), str(name), size * units.GiB,
                         old_format=False,
                         features=self.rbd.RBD_FEATURE_LAYERING)
        mock_client.__exit__(None, None, None).AndReturn(None)

        self.mox.ReplayAll()

        self.driver.create_volume(volume)

    @mock.patch('cinder.volume.drivers.rbd.rados')
    @mock.patch('cinder.volume.drivers.rbd.rbd')
    def test_delete_volume(self, _mock_rbd, _mock_rados):
        name = u'volume-00000001'
        volume = dict(name=name)

        _mock_rbd.Image = mock_rbd.Image
        _mock_rbd.Image.list_snaps = mock.Mock()
        _mock_rbd.Image.list_snaps.return_value = []
        _mock_rbd.Image.unprotect_snap = mock.Mock()

        _mock_rbd.RBD = mock_rbd.RBD
        _mock_rbd.RBD.remove = mock.Mock()

        self.driver.rbd = _mock_rbd
        self.driver.rados = _mock_rados

        mpo = mock.patch.object
        with mpo(driver, 'RADOSClient') as mock_rados_client:
            with mpo(self.driver, '_get_clone_info') as mock_get_clone_info:
                mock_get_clone_info.return_value = (None, None, None)
                with mpo(self.driver,
                         '_delete_backup_snaps') as mock_del_backup_snaps:
                    self.driver.delete_volume(volume)

                    self.assertTrue(mock_get_clone_info.called)
                    self.assertTrue(_mock_rbd.Image.list_snaps.called)
                    self.assertTrue(mock_rados_client.called)
                    self.assertTrue(mock_del_backup_snaps.called)
                    self.assertFalse(mock_rbd.Image.unprotect_snap.called)
                    self.assertTrue(_mock_rbd.RBD.remove.called)

    @mock.patch('cinder.volume.drivers.rbd.rbd')
    def test_delete_volume_not_found(self, _mock_rbd):
        name = u'volume-00000001'
        volume = dict(name=name)

        class MyMockException(Exception):
            pass

        _mock_rbd.RBD = mock_rbd.RBD
        _mock_rbd.ImageNotFound = MyMockException
        _mock_rbd.Image.side_effect = _mock_rbd.ImageNotFound

        mpo = mock.patch.object
        with mpo(self.driver, 'rbd', _mock_rbd):
            with mpo(driver, 'RADOSClient'):
                self.assertIsNone(self.driver.delete_volume(volume))
                _mock_rbd.Image.assert_called_once()

    @mock.patch('cinder.volume.drivers.rbd.rados')
    @mock.patch('cinder.volume.drivers.rbd.rbd')
    def test_delete_busy_volume(self, _mock_rbd, _mock_rados):
        name = u'volume-00000001'
        volume = dict(name=name)

        _mock_rbd.Image = mock_rbd.Image
        _mock_rbd.Image.list_snaps = mock.Mock()
        _mock_rbd.Image.list_snaps.return_value = []
        _mock_rbd.Image.unprotect_snap = mock.Mock()

        class MyMockException(Exception):
            pass

        _mock_rbd.RBD = mock_rbd.RBD
        _mock_rbd.ImageBusy = MyMockException
        _mock_rbd.RBD.remove = mock.Mock()
        _mock_rbd.RBD.remove.side_effect = _mock_rbd.ImageBusy

        self.driver.rbd = _mock_rbd
        self.driver.rados = _mock_rados

        mpo = mock.patch.object
        with mpo(driver, 'RADOSClient') as mock_rados_client:
            with mpo(self.driver, '_get_clone_info') as mock_get_clone_info:
                mock_get_clone_info.return_value = (None, None, None)
                with mpo(self.driver,
                         '_delete_backup_snaps') as mock_del_backup_snaps:

                    self.assertRaises(exception.VolumeIsBusy,
                                      self.driver.delete_volume,
                                      volume)

                    self.assertTrue(mock_get_clone_info.called)
                    self.assertTrue(_mock_rbd.Image.list_snaps.called)
                    self.assertTrue(mock_rados_client.called)
                    self.assertTrue(mock_del_backup_snaps.called)
                    self.assertFalse(mock_rbd.Image.unprotect_snap.called)
                    self.assertTrue(_mock_rbd.RBD.remove.called)

    def test_create_snapshot(self):
        vol_name = u'volume-00000001'
        snap_name = u'snapshot-name'
        snapshot = dict(volume_name=vol_name, name=snap_name)
        mock_proxy = self.mox.CreateMockAnything()
        self.mox.StubOutWithMock(driver, 'RBDVolumeProxy')

        driver.RBDVolumeProxy(self.driver, vol_name) \
            .AndReturn(mock_proxy)
        mock_proxy.__enter__().AndReturn(mock_proxy)
        mock_proxy.create_snap(str(snap_name))
        self.rbd.RBD_FEATURE_LAYERING = 1
        mock_proxy.protect_snap(str(snap_name))
        mock_proxy.__exit__(None, None, None).AndReturn(None)

        self.mox.ReplayAll()

        self.driver.create_snapshot(snapshot)

    def test_delete_snapshot(self):
        vol_name = u'volume-00000001'
        snap_name = u'snapshot-name'
        snapshot = dict(volume_name=vol_name, name=snap_name)
        mock_proxy = self.mox.CreateMockAnything()
        self.mox.StubOutWithMock(driver, 'RBDVolumeProxy')

        driver.RBDVolumeProxy(self.driver, vol_name) \
            .AndReturn(mock_proxy)
        mock_proxy.__enter__().AndReturn(mock_proxy)
        self.rbd.RBD_FEATURE_LAYERING = 1
        mock_proxy.unprotect_snap(str(snap_name))
        mock_proxy.remove_snap(str(snap_name))
        mock_proxy.__exit__(None, None, None).AndReturn(None)

        self.mox.ReplayAll()

        self.driver.delete_snapshot(snapshot)

    def test_create_cloned_volume(self):
        src_name = u'volume-00000001'
        dst_name = u'volume-00000002'

        # Setup librbd stubs
        self.stubs.Set(self.driver, 'rados', mock_rados)
        self.stubs.Set(self.driver, 'rbd', mock_rbd)

        self.driver.rbd.RBD_FEATURE_LAYERING = 1

        class mock_client(object):
            def __init__(self, *args, **kwargs):
                self.ioctx = None

            def __enter__(self, *args, **kwargs):
                return self

            def __exit__(self, type_, value, traceback):
                pass

        self.stubs.Set(driver, 'RADOSClient', mock_client)

        def mock_clone(*args, **kwargs):
            pass

        self.stubs.Set(self.driver.rbd.RBD, 'clone', mock_clone)
        self.stubs.Set(self.driver.rbd.Image, 'list_snaps',
                       lambda *args: [{'name': 'snap1'}, {'name': 'snap2'}])
        self.stubs.Set(self.driver.rbd.Image, 'parent_info',
                       lambda *args: (None, None, None))
        self.stubs.Set(self.driver.rbd.Image, 'protect_snap',
                       lambda *args: None)

        self.driver.create_cloned_volume(dict(name=dst_name),
                                         dict(name=src_name))

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

    def test_cloneable(self):
        self.stubs.Set(self.driver, '_get_fsid', lambda: 'abc')
        location = 'rbd://abc/pool/image/snap'
        mock_proxy = self.mox.CreateMockAnything()
        self.mox.StubOutWithMock(driver, 'RBDVolumeProxy')

        driver.RBDVolumeProxy(self.driver, 'image',
                              pool='pool',
                              snapshot='snap',
                              read_only=True).AndReturn(mock_proxy)
        mock_proxy.__enter__().AndReturn(mock_proxy)
        mock_proxy.__exit__(None, None, None).AndReturn(None)

        self.mox.ReplayAll()

        self.assertTrue(
            self.driver._is_cloneable(location, {'disk_format': 'raw'}))

    def test_uncloneable_different_fsid(self):
        self.stubs.Set(self.driver, '_get_fsid', lambda: 'abc')
        location = 'rbd://def/pool/image/snap'
        self.assertFalse(
            self.driver._is_cloneable(location, {'disk_format': 'raw'}))

    def test_uncloneable_unreadable(self):
        self.stubs.Set(self.driver, '_get_fsid', lambda: 'abc')
        location = 'rbd://abc/pool/image/snap'
        self.stubs.Set(self.rbd, 'Error', test.TestingException)
        self.mox.StubOutWithMock(driver, 'RBDVolumeProxy')

        driver.RBDVolumeProxy(self.driver, 'image',
                              pool='pool',
                              snapshot='snap',
                              read_only=True).AndRaise(test.TestingException)

        self.mox.ReplayAll()

        self.assertFalse(
            self.driver._is_cloneable(location, {'disk_format': 'raw'}))

    def test_uncloneable_bad_format(self):
        self.stubs.Set(self.driver, '_get_fsid', lambda: 'abc')
        location = 'rbd://abc/pool/image/snap'
        formats = ['qcow2', 'vmdk', 'vdi']
        for f in formats:
            self.assertFalse(
                self.driver._is_cloneable(location, {'disk_format': f}))

    def _copy_image(self):
        @contextlib.contextmanager
        def fake_temp_file(dir):
            class FakeTmp:
                def __init__(self, name):
                    self.name = name
            yield FakeTmp('test')

        def fake_fetch_to_raw(ctx, image_service, image_id, path, blocksize,
                              size=None):
            pass

        self.stubs.Set(tempfile, 'NamedTemporaryFile', fake_temp_file)
        self.stubs.Set(os.path, 'exists', lambda x: True)
        self.stubs.Set(image_utils, 'fetch_to_raw', fake_fetch_to_raw)
        self.stubs.Set(self.driver, 'delete_volume', lambda x: None)
        self.stubs.Set(self.driver, '_resize', lambda x: None)
        self.driver.copy_image_to_volume(None, {'name': 'test',
                                                'size': 1},
                                         FakeImageService(), None)

    def test_copy_image_no_volume_tmp(self):
        self.configuration.volume_tmp_dir = None
        self._copy_image()

    def test_copy_image_volume_tmp(self):
        self.configuration.volume_tmp_dir = '/var/run/cinder/tmp'
        self._copy_image()

    def test_update_volume_stats(self):
        self.stubs.Set(self.driver.configuration, 'safe_get', lambda x: 'RBD')
        mock_client = self.mox.CreateMockAnything()
        self.mox.StubOutWithMock(driver, 'RADOSClient')

        driver.RADOSClient(self.driver).AndReturn(mock_client)
        mock_client.__enter__().AndReturn(mock_client)
        self.mox.StubOutWithMock(mock_client, 'cluster')
        mock_client.cluster.get_cluster_stats().AndReturn(dict(
            kb=1234567890,
            kb_used=4567890,
            kb_avail=1000000000,
            num_objects=4683))
        mock_client.__exit__(None, None, None).AndReturn(None)

        self.mox.ReplayAll()

        expected = dict(
            volume_backend_name='RBD',
            vendor_name='Open Source',
            driver_version=self.driver.VERSION,
            storage_protocol='ceph',
            total_capacity_gb=1177,
            free_capacity_gb=953,
            reserved_percentage=0)
        actual = self.driver.get_volume_stats(True)
        self.assertDictMatch(expected, actual)

    def test_update_volume_stats_error(self):
        self.stubs.Set(self.driver.configuration, 'safe_get', lambda x: 'RBD')
        mock_client = self.mox.CreateMockAnything()
        self.mox.StubOutWithMock(driver, 'RADOSClient')

        driver.RADOSClient(self.driver).AndReturn(mock_client)
        mock_client.__enter__().AndReturn(mock_client)
        self.mox.StubOutWithMock(mock_client, 'cluster')
        self.stubs.Set(self.rados, 'Error', test.TestingException)
        mock_client.cluster.get_cluster_stats().AndRaise(test.TestingException)
        mock_client.__exit__(test.TestingException,
                             mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(None)

        self.mox.ReplayAll()

        expected = dict(
            volume_backend_name='RBD',
            vendor_name='Open Source',
            driver_version=self.driver.VERSION,
            storage_protocol='ceph',
            total_capacity_gb='unknown',
            free_capacity_gb='unknown',
            reserved_percentage=0)
        actual = self.driver.get_volume_stats(True)
        self.assertDictMatch(expected, actual)

    def test_get_mon_addrs(self):
        self.stubs.Set(self.driver, '_execute',
                       lambda *a: (CEPH_MON_DUMP, ''))
        hosts = ['::1', '::1', '::1', '127.0.0.1', 'example.com']
        ports = ['6789', '6790', '6791', '6792', '6791']
        self.assertEqual((hosts, ports), self.driver._get_mon_addrs())

    def test_initialize_connection(self):
        name = 'volume-00000001'
        hosts = ['::1', '::1', '::1', '127.0.0.1', 'example.com']
        ports = ['6789', '6790', '6791', '6792', '6791']
        self.stubs.Set(self.driver, '_get_mon_addrs', lambda: (hosts, ports))
        expected = {
            'driver_volume_type': 'rbd',
            'data': {
                'name': '%s/%s' % (self.configuration.rbd_pool,
                                   name),
                'hosts': hosts,
                'ports': ports,
                'auth_enabled': False,
                'auth_username': None,
                'secret_type': 'ceph',
                'secret_uuid': None, }
        }
        actual = self.driver.initialize_connection(dict(name=name), None)
        self.assertDictMatch(expected, actual)

    def test_clone(self):
        name = u'volume-00000001'
        volume = dict(name=name)
        src_pool = u'images'
        src_image = u'image-name'
        src_snap = u'snapshot-name'
        mock_src_client = self.mox.CreateMockAnything()
        mock_dst_client = self.mox.CreateMockAnything()
        mock_rbd = self.mox.CreateMockAnything()
        self.mox.StubOutWithMock(driver, 'RADOSClient')

        driver.RADOSClient(self.driver, src_pool).AndReturn(mock_src_client)
        mock_src_client.__enter__().AndReturn(mock_src_client)
        driver.RADOSClient(self.driver).AndReturn(mock_dst_client)
        mock_dst_client.__enter__().AndReturn(mock_dst_client)
        self.rbd.RBD_FEATURE_LAYERING = 1
        self.rbd.RBD().AndReturn(mock_rbd)
        mock_rbd.clone(mox.IgnoreArg(),
                       str(src_image),
                       str(src_snap),
                       mox.IgnoreArg(),
                       str(name),
                       features=self.rbd.RBD_FEATURE_LAYERING)
        mock_dst_client.__exit__(None, None, None).AndReturn(None)
        mock_src_client.__exit__(None, None, None).AndReturn(None)

        self.mox.ReplayAll()

        self.driver._clone(volume, src_pool, src_image, src_snap)

    def test_extend_volume(self):
        fake_name = u'volume-00000001'
        fake_size = '20'
        fake_vol = {'project_id': 'testprjid', 'name': fake_name,
                    'size': fake_size,
                    'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66'}

        self.mox.StubOutWithMock(self.driver, '_resize')
        size = int(fake_size) * units.GiB
        self.driver._resize(fake_vol, size=size)

        self.mox.ReplayAll()
        self.driver.extend_volume(fake_vol, fake_size)

        self.mox.VerifyAll()

    def test_rbd_volume_proxy_init(self):
        name = u'volume-00000001'
        snap = u'snapshot-name'
        self.stubs.Set(self.driver, '_connect_to_rados',
                       lambda x: (None, None))
        self.mox.StubOutWithMock(self.driver, '_disconnect_from_rados')

        # no snapshot
        self.rbd.Image(None, str(name), snapshot=None, read_only=False) \
                .AndReturn(None)
        # snapshot
        self.rbd.Image(None, str(name), snapshot=str(snap), read_only=True) \
                .AndReturn(None)
        # error causes disconnect
        self.stubs.Set(self.rbd, 'Error', test.TestingException)
        self.rbd.Image(None, str(name), snapshot=None, read_only=False) \
                .AndRaise(test.TestingException)
        self.driver._disconnect_from_rados(None, None)

        self.mox.ReplayAll()

        driver.RBDVolumeProxy(self.driver, name)
        driver.RBDVolumeProxy(self.driver, name, snapshot=snap, read_only=True)
        self.assertRaises(test.TestingException,
                          driver.RBDVolumeProxy, self.driver, name)

    def test_connect_to_rados(self):
        mock_client = self.mox.CreateMockAnything()
        mock_ioctx = self.mox.CreateMockAnything()
        self.stubs.Set(self.rados, 'Error', test.TestingException)

        # default configured pool
        self.rados.Rados(rados_id=None, conffile=None).AndReturn(mock_client)
        mock_client.connect()
        mock_client.open_ioctx('rbd').AndReturn(mock_ioctx)

        # different pool
        self.rados.Rados(rados_id=None, conffile=None).AndReturn(mock_client)
        mock_client.connect()
        mock_client.open_ioctx('images').AndReturn(mock_ioctx)

        # error
        self.rados.Rados(rados_id=None, conffile=None).AndReturn(mock_client)
        mock_client.connect()
        mock_client.open_ioctx('rbd').AndRaise(test.TestingException)
        mock_client.shutdown()

        self.mox.ReplayAll()

        self.assertEqual((mock_client, mock_ioctx),
                         self.driver._connect_to_rados())
        self.assertEqual((mock_client, mock_ioctx),
                         self.driver._connect_to_rados('images'))
        self.assertRaises(test.TestingException, self.driver._connect_to_rados)


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
            self.assertTrue(self.meta.image.flush.called)
            self.meta.image.flush.reset_mock()
            # this should be caught and logged silently.
            self.meta.image.flush.side_effect = AttributeError
            self.rbd_wrapper.flush()
            self.assertTrue(self.meta.image.flush.called)
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
        def mock_clone_image(volume, image_location, image_id, image_meta):
            self.called.append('clone_image')
            if clone_error:
                raise exception.CinderException()
            else:
                return {'provider_location': None}, True

        # See tests.image.fake for image types.
        if raw:
            image_id = '155d900f-4e14-4e4c-a73d-069cbf4541e6'
        else:
            image_id = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'

        volume_id = 1

        # creating volume testdata
        db.volume_create(self.context,
                         {'id': volume_id,
                          'updated_at': timeutils.utcnow(),
                          'display_description': 'Test Desc',
                          'size': 20,
                          'status': 'creating',
                          'instance_uuid': None,
                          'host': 'dummy'})

        mpo = mock.patch.object
        with mpo(self.volume.driver, 'create_volume') as mock_create_volume:
            with mpo(self.volume.driver, 'clone_image', mock_clone_image):
                with mpo(create_volume.CreateVolumeFromSpecTask,
                         '_copy_image_to_volume') as mock_copy_image_to_volume:

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

                    self.assertEqual(self.called, ['clone_image'])
                    mock_create_volume.assert_called()
                    mock_copy_image_to_volume.assert_called()

    def test_create_vol_from_image_status_available(self):
        """Clone raw image then verify volume is in available state."""
        self._create_volume_from_image('available', raw=True)

    def test_create_vol_from_non_raw_image_status_available(self):
        """Clone non-raw image then verify volume is in available state."""
        self._create_volume_from_image('available', raw=False)

    def test_create_vol_from_image_status_error(self):
        """Fail to clone raw image then verify volume is in error state."""
        self._create_volume_from_image('error', raw=True, clone_error=True)

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
        mpo = mock.patch.object
        with mpo(driver, '_is_cloneable', lambda *args: True):
            with mpo(driver, '_parse_location', lambda x: (1, 2, 3, 4)):
                with mpo(driver, '_clone') as mock_clone:
                    with mpo(driver, '_resize') as mock_resize:
                        image_loc = (mock.Mock(), mock.Mock())
                        actual = driver.clone_image(mock.Mock(),
                                                    image_loc,
                                                    mock.Mock(),
                                                    {'disk_format': 'raw'})
                        self.assertEqual(expected, actual)
                        mock_clone.assert_called()
                        mock_resize.assert_called()
