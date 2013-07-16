# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
import mox
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
        self.assertEqual(None, driver.ascii_str(None))
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

        self.rados = self.mox.CreateMockAnything()
        self.rbd = self.mox.CreateMockAnything()
        self.driver = driver.RBDDriver(execute=fake_execute,
                                       configuration=self.configuration,
                                       rados=self.rados,
                                       rbd=self.rbd)

    def test_create_volume(self):
        name = u'volume-00000001'
        size = 1
        volume = dict(name=name, size=size)
        mock_client = self.mox.CreateMockAnything()
        self.mox.StubOutWithMock(driver, 'RADOSClient')

        driver.RADOSClient(self.driver).AndReturn(mock_client)
        mock_client.__enter__().AndReturn(mock_client)
        self.rbd.RBD_FEATURE_LAYERING = 1
        mock_rbd = self.mox.CreateMockAnything()
        self.rbd.RBD().AndReturn(mock_rbd)
        mock_rbd.create(mox.IgnoreArg(), str(name), size * 1024 ** 3,
                        old_format=False,
                        features=self.rbd.RBD_FEATURE_LAYERING)
        mock_client.__exit__(None, None, None).AndReturn(None)

        self.mox.ReplayAll()

        self.driver.create_volume(volume)

    def test_delete_volume(self):
        name = u'volume-00000001'
        volume = dict(name=name)
        mock_client = self.mox.CreateMockAnything()
        self.mox.StubOutWithMock(driver, 'RADOSClient')

        driver.RADOSClient(self.driver).AndReturn(mock_client)
        mock_client.__enter__().AndReturn(mock_client)
        mock_rbd = self.mox.CreateMockAnything()
        self.rbd.RBD().AndReturn(mock_rbd)
        mock_rbd.remove(mox.IgnoreArg(), str(name))
        mock_client.__exit__(None, None, None).AndReturn(None)

        self.mox.ReplayAll()

        self.driver.delete_volume(volume)

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
        mock_proxy = self.mox.CreateMockAnything()
        mock_proxy.ioctx = self.mox.CreateMockAnything()
        self.mox.StubOutWithMock(driver, 'RBDVolumeProxy')

        driver.RBDVolumeProxy(self.driver, src_name, read_only=True) \
            .AndReturn(mock_proxy)
        mock_proxy.__enter__().AndReturn(mock_proxy)
        mock_proxy.copy(mock_proxy.ioctx, str(dst_name))
        mock_proxy.__exit__(None, None, None).AndReturn(None)

        self.mox.ReplayAll()

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
            self.assertFalse(self.driver._is_cloneable(loc))

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

        self.assertTrue(self.driver._is_cloneable(location))

    def test_uncloneable_different_fsid(self):
        self.stubs.Set(self.driver, '_get_fsid', lambda: 'abc')
        location = 'rbd://def/pool/image/snap'
        self.assertFalse(self.driver._is_cloneable(location))

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

        self.assertFalse(self.driver._is_cloneable(location))

    def _copy_image(self):
        @contextlib.contextmanager
        def fake_temp_file(dir):
            class FakeTmp:
                def __init__(self, name):
                    self.name = name
            yield FakeTmp('test')
        self.stubs.Set(tempfile, 'NamedTemporaryFile', fake_temp_file)
        self.stubs.Set(os.path, 'exists', lambda x: True)
        self.stubs.Set(image_utils, 'fetch_to_raw', lambda w, x, y, z: None)
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
            driver_version=driver.VERSION,
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
            driver_version=driver.VERSION,
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


class ManagedRBDTestCase(DriverTestCase):
    driver_name = "cinder.volume.drivers.rbd.RBDDriver"

    def setUp(self):
        super(ManagedRBDTestCase, self).setUp()
        fake_image.stub_out_image_service(self.stubs)

    def _clone_volume_from_image(self, expected_status,
                                 clone_works=True):
        """Try to clone a volume from an image, and check the status
        afterwards.
        """
        def fake_clone_image(volume, image_location):
            return True

        def fake_clone_error(volume, image_location):
            raise exception.CinderException()

        self.stubs.Set(self.volume.driver, '_is_cloneable', lambda x: True)
        if clone_works:
            self.stubs.Set(self.volume.driver, 'clone_image', fake_clone_image)
        else:
            self.stubs.Set(self.volume.driver, 'clone_image', fake_clone_error)

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
        try:
            if clone_works:
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

    def test_clone_image_status_available(self):
        """Verify that before cloning, an image is in the available state."""
        self._clone_volume_from_image('available', True)

    def test_clone_image_status_error(self):
        """Verify that before cloning, an image is in the available state."""
        self._clone_volume_from_image('error', False)

    def test_clone_success(self):
        self.stubs.Set(self.volume.driver, '_is_cloneable', lambda x: True)
        self.stubs.Set(self.volume.driver, 'clone_image', lambda a, b: True)
        image_id = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'
        self.assertTrue(self.volume.driver.clone_image({}, image_id))

    def test_clone_bad_image_id(self):
        self.stubs.Set(self.volume.driver, '_is_cloneable', lambda x: True)
        self.assertFalse(self.volume.driver.clone_image({}, None))

    def test_clone_uncloneable(self):
        self.stubs.Set(self.volume.driver, '_is_cloneable', lambda x: False)
        self.assertFalse(self.volume.driver.clone_image({}, 'dne'))
