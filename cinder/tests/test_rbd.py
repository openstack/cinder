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
from cinder.volume import configuration as conf
from cinder.volume.drivers.rbd import RBDDriver
from cinder.volume.drivers.rbd import VERSION as DRIVER_VERSION

LOG = logging.getLogger(__name__)


class FakeImageService:
    def download(self, context, image_id, path):
        pass

RADOS_DF_OUT = """
{
   "total_space" : "958931232",
   "total_used" : "123906196",
   "total_objects" : "4221",
   "total_avail" : "787024012",
   "pools" : [
      {
         "name" : "volumes",
         "categories" : [
            {
               "write_bytes" : "226833",
               "size_kb" : "17038386",
               "read_bytes" : "221865",
               "num_objects" : "4186",
               "name" : "",
               "size_bytes" : "17447306589",
               "write_kb" : "20302730",
               "num_object_copies" : "8372",
               "read_kb" : "30",
               "num_objects_unfound" : "0",
               "num_object_clones" : "9",
               "num_objects_missing_on_primary" : "0",
               "num_objects_degraded" : "0"
            }
         ],
         "id" : "4"
      }
   ]
}
"""


class RBDTestCase(test.TestCase):

    def setUp(self):
        super(RBDTestCase, self).setUp()

        def fake_execute(*args, **kwargs):
            return '', ''
        self._mox = mox.Mox()
        self.configuration = mox.MockObject(conf.Configuration)
        self.configuration.volume_tmp_dir = None
        self.configuration.rbd_pool = 'rbd'
        self.configuration.rbd_secret_uuid = None
        self.configuration.rbd_user = None
        self.configuration.append_config_values(mox.IgnoreArg())

        self.driver = RBDDriver(execute=fake_execute,
                                configuration=self.configuration)
        self._mox.ReplayAll()

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
        self.assertTrue(self.driver._is_cloneable(location))

    def test_uncloneable_different_fsid(self):
        self.stubs.Set(self.driver, '_get_fsid', lambda: 'abc')
        location = 'rbd://def/pool/image/snap'
        self.assertFalse(self.driver._is_cloneable(location))

    def test_uncloneable_unreadable(self):
        def fake_exc(*args):
            raise exception.ProcessExecutionError()
        self.stubs.Set(self.driver, '_get_fsid', lambda: 'abc')
        self.stubs.Set(self.driver, '_execute', fake_exc)
        location = 'rbd://abc/pool/image/snap'
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
        def fake_stats(*args):
            return RADOS_DF_OUT, ''
        self.stubs.Set(self.driver, '_execute', fake_stats)
        expected = dict(
            volume_backend_name='RBD',
            vendor_name='Open Source',
            driver_version=DRIVER_VERSION,
            storage_protocol='ceph',
            total_capacity_gb=914,
            free_capacity_gb=750,
            reserved_percentage=0)
        actual = self.driver.get_volume_stats(True)
        self.assertDictMatch(expected, actual)

    def test_update_volume_stats_error(self):
        def fake_exc(*args):
            raise exception.ProcessExecutionError()
        self.stubs.Set(self.driver, '_execute', fake_exc)
        expected = dict(
            volume_backend_name='RBD',
            vendor_name='Open Source',
            driver_version=DRIVER_VERSION,
            storage_protocol='ceph',
            total_capacity_gb='unknown',
            free_capacity_gb='unknown',
            reserved_percentage=0)
        actual = self.driver.get_volume_stats(True)
        self.assertDictMatch(expected, actual)


class ManagedRBDTestCase(DriverTestCase):
    driver_name = "cinder.volume.drivers.rbd.RBDDriver"

    def setUp(self):
        super(ManagedRBDTestCase, self).setUp()
        fake_image.stub_out_image_service(self.stubs)

    def _clone_volume_from_image(self, expected_status,
                                 clone_works=True):
        """Try to clone a volume from an image, and check the status
        afterwards"""
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
