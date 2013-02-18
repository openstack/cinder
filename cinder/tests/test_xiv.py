# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 IBM, Inc.
# Copyright (c) 2012 OpenStack LLC.
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
#
# Authors:
#   Erik Zaadi <erikz@il.ibm.com>
#   Avishay Traeger <avishay@il.ibm.com>

import mox

from cinder import exception
from cinder import flags
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers import xiv


FLAGS = flags.FLAGS

FAKE = "fake"
VOLUME = {'size': 16,
          'name': FAKE,
          'id': 1}

CONNECTOR = {'initiator': "iqn.2012-07.org.fake:01:948f189c4695", }


class XIVFakeProxyDriver(object):
    """Fake XIV Proxy Driver."""

    def __init__(self, xiv_info, logger, expt):
        """
        Initialize Proxy
        """

        self.xiv_info = xiv_info
        self.logger = logger
        self.exception = expt
        self.xiv_portal = \
            self.xiv_iqn = FAKE

        self.volumes = {}

    def setup(self, context):
        if self.xiv_info['xiv_user'] != FLAGS.san_login:
            raise self.exception.NotAuthorized()

        if self.xiv_info['xiv_address'] != FLAGS.san_ip:
            raise self.exception.HostNotFound(host='fake')

    def create_volume(self, volume):
        if volume['size'] > 100:
            raise self.exception.VolumeBackendAPIException(data='blah')
        self.volumes[volume['name']] = volume

    def volume_exists(self, volume):
        return self.volumes.get(volume['name'], None) is not None

    def delete_volume(self, volume):
        if self.volumes.get(volume['name'], None) is not None:
            del self.volumes[volume['name']]

    def initialize_connection(self, volume, connector):
        if not self.volume_exists(volume):
            raise self.exception.VolumeNotFound(volume_id=volume['id'])
        lun_id = volume['id']

        self.volumes[volume['name']]['attached'] = connector

        return {'driver_volume_type': 'iscsi',
                'data': {'target_discovered': True,
                         'target_discovered': True,
                         'target_portal': self.xiv_portal,
                         'target_iqn': self.xiv_iqn,
                         'target_lun': lun_id,
                         'volume_id': volume['id'],
                         'multipath': True,
                         'provider_location': "%s,1 %s %s" % (
                             self.xiv_portal,
                             self.xiv_iqn,
                             lun_id), },
                }

    def terminate_connection(self, volume, connector):
        if not self.volume_exists(volume):
            raise self.exception.VolumeNotFound(volume_id=volume['id'])
        if not self.is_volume_attached(volume, connector):
            raise self.exception.VolumeNotFoundForInstance(instance_id='fake')
        del self.volumes[volume['name']]['attached']

    def is_volume_attached(self, volume, connector):
        if not self.volume_exists(volume):
            raise self.exception.VolumeNotFound(volume_id=volume['id'])

        return (self.volumes[volume['name']].get('attached', None)
                == connector)


class XIVVolumeDriverTest(test.TestCase):
    """Test IBM XIV volume driver."""

    def setUp(self):
        """Initialize IVM XIV Driver."""
        super(XIVVolumeDriverTest, self).setUp()

        configuration = mox.MockObject(conf.Configuration)
        configuration.san_is_local = False
        configuration.append_config_values(mox.IgnoreArg())

        self.driver = xiv.XIVDriver(configuration=configuration)

    def test_initialized_should_set_xiv_info(self):
        """Test that the san flags are passed to the XIV proxy."""

        self.assertEquals(self.driver.xiv_proxy.xiv_info['xiv_user'],
                          FLAGS.san_login)
        self.assertEquals(self.driver.xiv_proxy.xiv_info['xiv_pass'],
                          FLAGS.san_password)
        self.assertEquals(self.driver.xiv_proxy.xiv_info['xiv_address'],
                          FLAGS.san_ip)
        self.assertEquals(self.driver.xiv_proxy.xiv_info['xiv_vol_pool'],
                          FLAGS.san_clustername)

    def test_setup_should_fail_if_credentials_are_invalid(self):
        """Test that the xiv_proxy validates credentials."""

        self.driver.xiv_proxy.xiv_info['xiv_user'] = 'invalid'
        self.assertRaises(exception.NotAuthorized, self.driver.do_setup, None)

    def test_setup_should_fail_if_connection_is_invalid(self):
        """Test that the xiv_proxy validates connection."""

        self.driver.xiv_proxy.xiv_info['xiv_address'] = 'invalid'
        self.assertRaises(exception.HostNotFound, self.driver.do_setup, None)

    def test_create_volume(self):
        """Test creating a volume."""

        self.driver.do_setup(None)
        self.driver.create_volume(VOLUME)
        has_volume = self.driver.xiv_proxy.volume_exists(VOLUME)
        self.assertTrue(has_volume)
        self.driver.delete_volume(VOLUME)

    def test_volume_exists(self):
        """Test the volume exist method with a volume that doesn't exist."""

        self.driver.do_setup(None)
        self.assertFalse(self.driver.xiv_proxy.volume_exists({'name': FAKE}))

    def test_delete_volume(self):
        """Verify that a volume is deleted."""

        self.driver.do_setup(None)
        self.driver.create_volume(VOLUME)
        self.driver.delete_volume(VOLUME)
        has_volume = self.driver.xiv_proxy.volume_exists(VOLUME)
        self.assertFalse(has_volume)

    def test_delete_volume_should_fail_for_not_existing_volume(self):
        """Verify that deleting a non-existing volume is OK."""

        self.driver.do_setup(None)
        self.driver.delete_volume(VOLUME)

    def test_create_volume_should_fail_if_no_pool_space_left(self):
        """Vertify that the xiv_proxy validates volume pool space."""

        self.driver.do_setup(None)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume,
                          {'name': FAKE,
                           'id': 1,
                           'size': 12000})

    def test_initialize_connection(self):
        """Test that inititialize connection attaches volume to host."""

        self.driver.do_setup(None)
        self.driver.create_volume(VOLUME)
        self.driver.initialize_connection(VOLUME, CONNECTOR)

        self.assertTrue(
            self.driver.xiv_proxy.is_volume_attached(VOLUME, CONNECTOR))

        self.driver.terminate_connection(VOLUME, CONNECTOR)
        self.driver.delete_volume(VOLUME)

    def test_initialize_connection_should_fail_for_non_existing_volume(self):
        """Verify that initialize won't work for non-existing volume."""

        self.driver.do_setup(None)
        self.assertRaises(exception.VolumeNotFound,
                          self.driver.initialize_connection,
                          VOLUME,
                          CONNECTOR)

    def test_terminate_connection(self):
        """Test terminating a connection."""

        self.driver.do_setup(None)
        self.driver.create_volume(VOLUME)
        self.driver.initialize_connection(VOLUME, CONNECTOR)
        self.driver.terminate_connection(VOLUME, CONNECTOR)

        self.assertFalse(self.driver.xiv_proxy.is_volume_attached(VOLUME,
                                                                  CONNECTOR))

        self.driver.delete_volume(VOLUME)

    def test_terminate_connection_should_fail_on_non_existing_volume(self):
        """Test that terminate won't work for non-existing volumes."""

        self.driver.do_setup(None)
        self.assertRaises(exception.VolumeNotFound,
                          self.driver.terminate_connection,
                          VOLUME,
                          CONNECTOR)

    def test_terminate_connection_should_fail_on_non_attached_volume(self):
        """Test that terminate won't work for volumes that are not attached."""

        self.driver.do_setup(None)
        self.driver.create_volume(VOLUME)

        self.assertRaises(exception.VolumeNotFoundForInstance,
                          self.driver.terminate_connection,
                          VOLUME,
                          CONNECTOR)

        self.driver.delete_volume(VOLUME)
