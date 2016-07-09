# Copyright (C) 2017 Dell Inc. or its subsidiaries.
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

import ddt
import mock
from oslo_config import cfg
from oslo_utils import importutils

from cinder import context
from cinder import exception
from cinder import objects
from cinder.objects import fields
from cinder import quota
from cinder import test
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import utils as tests_utils
from cinder.volume import api as volume_api
from cinder.volume import configuration as conf
from cinder.volume import driver
from cinder.volume import utils as volutils

GROUP_QUOTAS = quota.GROUP_QUOTAS
CONF = cfg.CONF


@ddt.ddt
class GroupManagerTestCase(test.TestCase):

    def setUp(self):
        super(GroupManagerTestCase, self).setUp()
        self.volume = importutils.import_object(CONF.volume_manager)
        self.configuration = mock.Mock(conf.Configuration)
        self.context = context.get_admin_context()
        self.context.user_id = fake.USER_ID
        self.project_id = fake.PROJECT3_ID
        self.context.project_id = self.project_id
        self.volume.driver.set_initialized()
        self.volume.stats = {'allocated_capacity_gb': 0,
                             'pools': {}}
        self.volume_api = volume_api.API()

    @mock.patch.object(GROUP_QUOTAS, "reserve",
                       return_value=["RESERVATION"])
    @mock.patch.object(GROUP_QUOTAS, "commit")
    @mock.patch.object(GROUP_QUOTAS, "rollback")
    @mock.patch.object(driver.VolumeDriver,
                       "delete_group",
                       return_value=({'status': (
                           fields.GroupStatus.DELETED)}, []))
    @mock.patch.object(driver.VolumeDriver,
                       "enable_replication",
                       return_value=(None, []))
    @mock.patch.object(driver.VolumeDriver,
                       "disable_replication",
                       return_value=(None, []))
    @mock.patch.object(driver.VolumeDriver,
                       "failover_replication",
                       return_value=(None, []))
    def test_replication_group(self, fake_failover_rep, fake_disable_rep,
                               fake_enable_rep, fake_delete_grp,
                               fake_rollback, fake_commit, fake_reserve):
        """Test enable, disable, and failover replication for group."""

        def fake_driver_create_grp(context, group):
            """Make sure that the pool is part of the host."""
            self.assertIn('host', group)
            host = group.host
            pool = volutils.extract_host(host, level='pool')
            self.assertEqual('fakepool', pool)
            return {'status': fields.GroupStatus.AVAILABLE,
                    'replication_status': fields.ReplicationStatus.DISABLING}

        self.mock_object(self.volume.driver, 'create_group',
                         fake_driver_create_grp)

        group = tests_utils.create_group(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            volume_type_ids=[fake.VOLUME_TYPE_ID],
            host='fakehost@fakedrv#fakepool',
            group_type_id=fake.GROUP_TYPE_ID)
        group = objects.Group.get_by_id(self.context, group.id)
        self.volume.create_group(self.context, group)
        self.assertEqual(
            group.id,
            objects.Group.get_by_id(context.get_admin_context(),
                                    group.id).id)

        self.volume.disable_replication(self.context, group)
        group = objects.Group.get_by_id(
            context.get_admin_context(), group.id)
        self.assertEqual(fields.ReplicationStatus.DISABLED,
                         group.replication_status)

        group.replication_status = fields.ReplicationStatus.ENABLING
        group.save()
        self.volume.enable_replication(self.context, group)
        group = objects.Group.get_by_id(
            context.get_admin_context(), group.id)
        self.assertEqual(fields.ReplicationStatus.ENABLED,
                         group.replication_status)

        group.replication_status = fields.ReplicationStatus.FAILING_OVER
        group.save()
        self.volume.failover_replication(self.context, group)
        group = objects.Group.get_by_id(
            context.get_admin_context(), group.id)
        self.assertEqual(fields.ReplicationStatus.FAILED_OVER,
                         group.replication_status)

        targets = self.volume.list_replication_targets(self.context, group)
        self.assertIn('replication_targets', targets)

        self.volume.delete_group(self.context, group)
        grp = objects.Group.get_by_id(
            context.get_admin_context(read_deleted='yes'), group.id)
        self.assertEqual(fields.GroupStatus.DELETED, grp.status)
        self.assertRaises(exception.NotFound,
                          objects.Group.get_by_id,
                          self.context,
                          group.id)
