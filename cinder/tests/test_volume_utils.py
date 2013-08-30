# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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

"""Tests For miscellaneous util methods used with volume."""


from oslo.config import cfg

from cinder import context
from cinder import db
from cinder.openstack.common import importutils
from cinder.openstack.common import log as logging
from cinder.openstack.common.notifier import api as notifier_api
from cinder.openstack.common.notifier import test_notifier
from cinder import test
from cinder.volume import utils as volume_utils


LOG = logging.getLogger(__name__)

CONF = cfg.CONF


class UsageInfoTestCase(test.TestCase):

    QUEUE_NAME = 'cinder-volume'
    HOSTNAME = 'my-host.com'
    HOSTIP = '10.0.0.1'
    BACKEND = 'test_backend'
    MULTI_AT_BACKEND = 'test_b@ckend'

    def setUp(self):
        super(UsageInfoTestCase, self).setUp()
        self.flags(connection_type='fake',
                   host='fake',
                   notification_driver=[test_notifier.__name__])
        self.volume = importutils.import_object(CONF.volume_manager)
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.snapshot_id = 'fake'
        self.volume_size = 0
        self.context = context.RequestContext(self.user_id, self.project_id)
        test_notifier.NOTIFICATIONS = []

    def tearDown(self):
        notifier_api._reset_drivers()
        super(UsageInfoTestCase, self).tearDown()

    def _create_volume(self, params={}):
        """Create a test volume."""
        vol = {}
        vol['snapshot_id'] = self.snapshot_id
        vol['user_id'] = self.user_id
        vol['project_id'] = self.project_id
        vol['host'] = CONF.host
        vol['availability_zone'] = CONF.storage_availability_zone
        vol['status'] = "creating"
        vol['attach_status'] = "detached"
        vol['size'] = self.volume_size
        vol.update(params)
        return db.volume_create(self.context, vol)['id']

    def test_notify_usage_exists(self):
        """Ensure 'exists' notification generates appropriate usage data."""
        volume_id = self._create_volume()
        volume = db.volume_get(self.context, volume_id)
        volume_utils.notify_usage_exists(self.context, volume)
        LOG.info("%r" % test_notifier.NOTIFICATIONS)
        self.assertEquals(len(test_notifier.NOTIFICATIONS), 1)
        msg = test_notifier.NOTIFICATIONS[0]
        self.assertEquals(msg['priority'], 'INFO')
        self.assertEquals(msg['event_type'], 'volume.exists')
        payload = msg['payload']
        self.assertEquals(payload['tenant_id'], self.project_id)
        self.assertEquals(payload['user_id'], self.user_id)
        self.assertEquals(payload['snapshot_id'], self.snapshot_id)
        self.assertEquals(payload['volume_id'], volume.id)
        self.assertEquals(payload['size'], self.volume_size)
        for attr in ('display_name', 'created_at', 'launched_at',
                     'status', 'audit_period_beginning',
                     'audit_period_ending'):
            self.assertIn(attr, payload)
        db.volume_destroy(context.get_admin_context(), volume['id'])

    def test_get_host_from_queue_simple(self):
        fullname = "%s.%s@%s" % (self.QUEUE_NAME, self.HOSTNAME, self.BACKEND)
        self.assertEquals(volume_utils.get_host_from_queue(fullname),
                          self.HOSTNAME)

    def test_get_host_from_queue_ip(self):
        fullname = "%s.%s@%s" % (self.QUEUE_NAME, self.HOSTIP, self.BACKEND)
        self.assertEquals(volume_utils.get_host_from_queue(fullname),
                          self.HOSTIP)

    def test_get_host_from_queue_multi_at_symbol(self):
        fullname = "%s.%s@%s" % (self.QUEUE_NAME, self.HOSTNAME,
                                 self.MULTI_AT_BACKEND)
        self.assertEquals(volume_utils.get_host_from_queue(fullname),
                          self.HOSTNAME)

    def test_get_host_from_queue_ip_multi_at_symbol(self):
        fullname = "%s.%s@%s" % (self.QUEUE_NAME, self.HOSTIP,
                                 self.MULTI_AT_BACKEND)
        self.assertEquals(volume_utils.get_host_from_queue(fullname),
                          self.HOSTIP)


class LVMVolumeDriverTestCase(test.TestCase):
    def test_convert_blocksize_option(self):
        # Test valid volume_dd_blocksize
        CONF.set_override('volume_dd_blocksize', '10M')
        bs, count = volume_utils._calculate_count(1024)
        self.assertEquals(bs, '10M')
        self.assertEquals(count, 103)

        CONF.set_override('volume_dd_blocksize', '1xBBB')
        bs, count = volume_utils._calculate_count(1024)
        self.assertEquals(bs, '1M')
        self.assertEquals(count, 1024)

        # Test 'volume_dd_blocksize' with fraction
        CONF.set_override('volume_dd_blocksize', '1.3M')
        bs, count = volume_utils._calculate_count(1024)
        self.assertEquals(bs, '1M')
        self.assertEquals(count, 1024)

        # Test zero-size 'volume_dd_blocksize'
        CONF.set_override('volume_dd_blocksize', '0M')
        bs, count = volume_utils._calculate_count(1024)
        self.assertEquals(bs, '1M')
        self.assertEquals(count, 1024)

        # Test negative 'volume_dd_blocksize'
        CONF.set_override('volume_dd_blocksize', '-1M')
        bs, count = volume_utils._calculate_count(1024)
        self.assertEquals(bs, '1M')
        self.assertEquals(count, 1024)

        # Test non-digital 'volume_dd_blocksize'
        CONF.set_override('volume_dd_blocksize', 'ABM')
        bs, count = volume_utils._calculate_count(1024)
        self.assertEquals(bs, '1M')
        self.assertEquals(count, 1024)
