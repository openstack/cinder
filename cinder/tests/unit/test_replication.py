# Copyright 2014 IBM Corp.
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
"""
Tests for Volume replication code.
"""

import mock
from oslo_config import cfg
from oslo_utils import importutils

from cinder import context
from cinder import db
from cinder import exception
from cinder import test
from cinder.tests.unit import utils as test_utils
from cinder.volume import driver


CONF = cfg.CONF


class VolumeReplicationTestCase(test.TestCase):
    def setUp(self):
        super(VolumeReplicationTestCase, self).setUp()
        self.ctxt = context.RequestContext('user', 'fake', False)
        self.adm_ctxt = context.RequestContext('admin', 'fake', True)
        self.manager = importutils.import_object(CONF.volume_manager)
        self.manager.host = 'test_host'
        self.manager.stats = {'allocated_capacity_gb': 0}
        self.driver_patcher = mock.patch.object(self.manager, 'driver',
                                                spec=driver.VolumeDriver)
        self.driver = self.driver_patcher.start()

    @mock.patch('cinder.utils.require_driver_initialized')
    def test_promote_replica_uninit_driver(self, _init):
        """Test promote replication when driver is not initialized."""
        _init.side_effect = exception.DriverNotInitialized
        vol = test_utils.create_volume(self.ctxt,
                                       status='available',
                                       replication_status='active')
        self.driver.promote_replica.return_value = None
        self.assertRaises(exception.DriverNotInitialized,
                          self.manager.promote_replica,
                          self.adm_ctxt,
                          vol['id'])

    def test_promote_replica(self):
        """Test promote replication."""
        vol = test_utils.create_volume(self.ctxt,
                                       status='available',
                                       replication_status='active')
        self.driver.promote_replica.return_value = \
            {'replication_status': 'inactive'}
        self.manager.promote_replica(self.adm_ctxt, vol['id'])
        vol_after = db.volume_get(self.ctxt, vol['id'])
        self.assertEqual('inactive', vol_after['replication_status'])

    def test_promote_replica_fail(self):
        """Test promote replication when promote fails."""
        vol = test_utils.create_volume(self.ctxt,
                                       status='available',
                                       replication_status='active')
        self.driver.promote_replica.side_effect = exception.CinderException
        self.assertRaises(exception.CinderException,
                          self.manager.promote_replica,
                          self.adm_ctxt,
                          vol['id'])

    def test_reenable_replication(self):
        """Test reenable replication."""
        vol = test_utils.create_volume(self.ctxt,
                                       status='available',
                                       replication_status='error')
        self.driver.reenable_replication.return_value = \
            {'replication_status': 'copying'}
        self.manager.reenable_replication(self.adm_ctxt, vol['id'])
        vol_after = db.volume_get(self.ctxt, vol['id'])
        self.assertEqual('copying', vol_after['replication_status'])

    @mock.patch('cinder.utils.require_driver_initialized')
    def test_reenable_replication_uninit_driver(self, _init):
        """Test reenable replication when driver is not initialized."""
        _init.side_effect = exception.DriverNotInitialized
        vol = test_utils.create_volume(self.ctxt,
                                       status='available',
                                       replication_status='error')
        self.assertRaises(exception.DriverNotInitialized,
                          self.manager.reenable_replication,
                          self.adm_ctxt,
                          vol['id'])

    def test_reenable_replication_fail(self):
        """Test promote replication when driver is not initialized."""
        vol = test_utils.create_volume(self.ctxt,
                                       status='available',
                                       replication_status='error')
        self.driver.reenable_replication.side_effect = \
            exception.CinderException
        self.assertRaises(exception.CinderException,
                          self.manager.reenable_replication,
                          self.adm_ctxt,
                          vol['id'])
