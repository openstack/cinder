# Copyright (C) 2016 EMC Corporation.
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

from oslo_config import cfg
from oslo_utils import importutils

from cinder import context
from cinder import db
from cinder import exception
from cinder import objects
from cinder.objects import fields
from cinder import quota
from cinder import test
from cinder.tests.unit import conf_fixture
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import utils as tests_utils
from cinder.volume import api as volume_api
from cinder.volume import configuration as conf
from cinder.volume import driver
from cinder.volume import utils as volutils

GROUP_QUOTAS = quota.GROUP_QUOTAS
CONF = cfg.CONF


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

    def test_delete_volume_in_group(self):
        """Test deleting a volume that's tied to a group fails."""
        volume_params = {'status': 'available',
                         'group_id': fake.GROUP_ID}
        volume = tests_utils.create_volume(self.context, **volume_params)
        self.assertRaises(exception.InvalidVolume,
                          self.volume_api.delete, self.context, volume)

    @mock.patch.object(GROUP_QUOTAS, "reserve",
                       return_value=["RESERVATION"])
    @mock.patch.object(GROUP_QUOTAS, "commit")
    @mock.patch.object(GROUP_QUOTAS, "rollback")
    @mock.patch.object(driver.VolumeDriver,
                       "delete_group",
                       return_value=({'status': (
                           fields.GroupStatus.DELETED)}, []))
    def test_create_delete_group(self, fake_delete_grp,
                                 fake_rollback,
                                 fake_commit, fake_reserve):
        """Test group can be created and deleted."""

        def fake_driver_create_grp(context, group):
            """Make sure that the pool is part of the host."""
            self.assertIn('host', group)
            host = group.host
            pool = volutils.extract_host(host, level='pool')
            self.assertEqual('fakepool', pool)
            return {'status': fields.GroupStatus.AVAILABLE}

        self.mock_object(self.volume.driver, 'create_group',
                         fake_driver_create_grp)

        group = tests_utils.create_group(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            volume_type_ids=[fake.VOLUME_TYPE_ID],
            host='fakehost@fakedrv#fakepool',
            group_type_id=fake.GROUP_TYPE_ID)
        group = objects.Group.get_by_id(self.context, group.id)
        self.assertEqual(0, len(self.notifier.notifications),
                         self.notifier.notifications)
        self.volume.create_group(self.context, group)
        self.assertEqual(2, len(self.notifier.notifications),
                         self.notifier.notifications)
        msg = self.notifier.notifications[0]
        self.assertEqual('group.create.start', msg['event_type'])
        expected = {
            'status': fields.GroupStatus.AVAILABLE,
            'name': 'test_group',
            'availability_zone': 'nova',
            'tenant_id': self.context.project_id,
            'created_at': 'DONTCARE',
            'user_id': fake.USER_ID,
            'group_id': group.id,
            'group_type': fake.GROUP_TYPE_ID
        }
        self.assertDictMatch(expected, msg['payload'])
        msg = self.notifier.notifications[1]
        self.assertEqual('group.create.end', msg['event_type'])
        self.assertDictMatch(expected, msg['payload'])
        self.assertEqual(
            group.id,
            objects.Group.get_by_id(context.get_admin_context(),
                                    group.id).id)

        self.volume.delete_group(self.context, group)
        grp = objects.Group.get_by_id(
            context.get_admin_context(read_deleted='yes'), group.id)
        self.assertEqual(fields.GroupStatus.DELETED, grp.status)
        self.assertEqual(4, len(self.notifier.notifications),
                         self.notifier.notifications)
        msg = self.notifier.notifications[2]
        self.assertEqual('group.delete.start', msg['event_type'])
        self.assertDictMatch(expected, msg['payload'])
        msg = self.notifier.notifications[3]
        self.assertEqual('group.delete.end', msg['event_type'])
        expected['status'] = fields.GroupStatus.DELETED
        self.assertDictMatch(expected, msg['payload'])
        self.assertRaises(exception.NotFound,
                          objects.Group.get_by_id,
                          self.context,
                          group.id)

    @mock.patch.object(GROUP_QUOTAS, "reserve",
                       return_value=["RESERVATION"])
    @mock.patch.object(GROUP_QUOTAS, "commit")
    @mock.patch.object(GROUP_QUOTAS, "rollback")
    @mock.patch.object(driver.VolumeDriver,
                       "create_group",
                       return_value={'status': 'available'})
    @mock.patch.object(driver.VolumeDriver,
                       "update_group")
    def test_update_group(self, fake_update_grp,
                          fake_create_grp, fake_rollback,
                          fake_commit, fake_reserve):
        """Test group can be updated."""
        group = tests_utils.create_group(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            volume_type_ids=[fake.VOLUME_TYPE_ID],
            group_type_id=fake.GROUP_TYPE_ID,
            host=CONF.host)
        self.volume.create_group(self.context, group)

        volume = tests_utils.create_volume(
            self.context,
            group_id=group.id,
            volume_type_id=fake.VOLUME_TYPE_ID,
            status='available',
            host=group.host)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)

        volume2 = tests_utils.create_volume(
            self.context,
            group_id=None,
            volume_type_id=fake.VOLUME_TYPE_ID,
            status='available',
            host=group.host)
        volume_id2 = volume2['id']
        self.volume.create_volume(self.context, volume_id2)

        fake_update_grp.return_value = (
            {'status': fields.GroupStatus.AVAILABLE},
            [{'id': volume_id2, 'status': 'available'}],
            [{'id': volume_id, 'status': 'available'}])

        self.volume.update_group(self.context, group,
                                 add_volumes=volume_id2,
                                 remove_volumes=volume_id)
        grp = objects.Group.get_by_id(self.context, group.id)
        expected = {
            'status': fields.GroupStatus.AVAILABLE,
            'name': 'test_group',
            'availability_zone': 'nova',
            'tenant_id': self.context.project_id,
            'created_at': 'DONTCARE',
            'user_id': fake.USER_ID,
            'group_id': group.id,
            'group_type': fake.GROUP_TYPE_ID
        }
        self.assertEqual(fields.GroupStatus.AVAILABLE, grp.status)
        self.assertEqual(10, len(self.notifier.notifications),
                         self.notifier.notifications)
        msg = self.notifier.notifications[6]
        self.assertEqual('group.update.start', msg['event_type'])
        self.assertDictMatch(expected, msg['payload'])
        msg = self.notifier.notifications[8]
        self.assertEqual('group.update.end', msg['event_type'])
        self.assertDictMatch(expected, msg['payload'])
        grpvolumes = db.volume_get_all_by_generic_group(self.context, group.id)
        grpvol_ids = [grpvol['id'] for grpvol in grpvolumes]
        # Verify volume is removed.
        self.assertNotIn(volume_id, grpvol_ids)
        # Verify volume is added.
        self.assertIn(volume_id2, grpvol_ids)

        volume3 = tests_utils.create_volume(
            self.context,
            group_id=None,
            host=group.host,
            volume_type_id=fake.VOLUME_TYPE_ID,
            status='wrong-status')
        volume_id3 = volume3['id']

        volume_get_orig = self.volume.db.volume_get
        self.volume.db.volume_get = mock.Mock(
            return_value={'status': 'wrong_status',
                          'id': volume_id3})
        # Try to add a volume in wrong status
        self.assertRaises(exception.InvalidVolume,
                          self.volume.update_group,
                          self.context,
                          group,
                          add_volumes=volume_id3,
                          remove_volumes=None)
        self.volume.db.volume_get.reset_mock()
        self.volume.db.volume_get = volume_get_orig

    @mock.patch.object(driver.VolumeDriver,
                       "create_group",
                       return_value={'status': 'available'})
    @mock.patch.object(driver.VolumeDriver,
                       "delete_group",
                       return_value=({'status': 'deleted'}, []))
    @mock.patch.object(driver.VolumeDriver,
                       "create_group_snapshot",
                       return_value={'status': 'available'})
    @mock.patch.object(driver.VolumeDriver,
                       "delete_group_snapshot",
                       return_value=({'status': 'deleted'}, []))
    @mock.patch.object(driver.VolumeDriver,
                       "create_group_from_src",
                       return_value=(None, None))
    @mock.patch('cinder.volume.drivers.lvm.LVMVolumeDriver.'
                'create_volume_from_snapshot')
    @mock.patch('cinder.volume.drivers.lvm.LVMVolumeDriver.'
                'create_cloned_volume')
    def test_create_group_from_src(self,
                                   mock_create_cloned_vol,
                                   mock_create_vol_from_snap,
                                   mock_create_from_src,
                                   mock_delete_grpsnap,
                                   mock_create_grpsnap,
                                   mock_delete_grp,
                                   mock_create_grp):
        """Test group can be created and deleted."""
        group = tests_utils.create_group(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            status=fields.GroupStatus.AVAILABLE,
            volume_type_ids=[fake.VOLUME_TYPE_ID],
            group_type_id=fake.GROUP_TYPE_ID,
            host=CONF.host)
        volume = tests_utils.create_volume(
            self.context,
            group_id=group.id,
            status='available',
            host=group.host,
            volume_type_id=fake.VOLUME_TYPE_ID,
            size=1)
        volume_id = volume['id']
        group_snapshot_returns = self._create_group_snapshot(group.id,
                                                             [volume_id])
        group_snapshot = group_snapshot_returns[0]
        snapshot_id = group_snapshot_returns[1][0]['id']

        # Create group from source group snapshot.
        group2 = tests_utils.create_group(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            group_snapshot_id=group_snapshot.id,
            volume_type_ids=[fake.VOLUME_TYPE_ID],
            group_type_id=fake.GROUP_TYPE_ID,
            host=CONF.host)
        group2 = objects.Group.get_by_id(self.context, group2.id)
        volume2 = tests_utils.create_volume(
            self.context,
            group_id=group2.id,
            snapshot_id=snapshot_id,
            status='available',
            host=group2.host,
            volume_type_id=fake.VOLUME_TYPE_ID)
        self.volume.create_volume(self.context, volume2.id, volume=volume2)
        self.volume.create_group_from_src(
            self.context, group2, group_snapshot=group_snapshot)
        grp2 = objects.Group.get_by_id(self.context, group2.id)
        expected = {
            'status': fields.GroupStatus.AVAILABLE,
            'name': 'test_group',
            'availability_zone': 'nova',
            'tenant_id': self.context.project_id,
            'created_at': 'DONTCARE',
            'user_id': fake.USER_ID,
            'group_id': group2.id,
            'group_type': fake.GROUP_TYPE_ID,
        }
        self.assertEqual(fields.GroupStatus.AVAILABLE, grp2.status)
        self.assertEqual(group2.id, grp2['id'])
        self.assertEqual(group_snapshot.id, grp2['group_snapshot_id'])
        self.assertIsNone(grp2['source_group_id'])

        msg = self.notifier.notifications[2]
        self.assertEqual('group.create.start', msg['event_type'])
        self.assertDictMatch(expected, msg['payload'])
        msg = self.notifier.notifications[4]
        self.assertEqual('group.create.end', msg['event_type'])
        self.assertDictMatch(expected, msg['payload'])

        if len(self.notifier.notifications) > 6:
            self.assertFalse(self.notifier.notifications[6],
                             self.notifier.notifications)
        self.assertEqual(6, len(self.notifier.notifications),
                         self.notifier.notifications)

        self.volume.delete_group(self.context, group2)

        if len(self.notifier.notifications) > 9:
            self.assertFalse(self.notifier.notifications[10],
                             self.notifier.notifications)
        self.assertEqual(9, len(self.notifier.notifications),
                         self.notifier.notifications)

        msg = self.notifier.notifications[6]
        self.assertEqual('group.delete.start', msg['event_type'])
        expected['status'] = fields.GroupStatus.AVAILABLE
        self.assertDictMatch(expected, msg['payload'])
        msg = self.notifier.notifications[8]
        self.assertEqual('group.delete.end', msg['event_type'])
        expected['status'] = fields.GroupStatus.DELETED
        self.assertDictMatch(expected, msg['payload'])

        grp2 = objects.Group.get_by_id(
            context.get_admin_context(read_deleted='yes'), group2.id)
        self.assertEqual(fields.GroupStatus.DELETED, grp2.status)
        self.assertRaises(exception.NotFound,
                          objects.Group.get_by_id,
                          self.context,
                          group2.id)

        # Create group from source group
        group3 = tests_utils.create_group(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            source_group_id=group.id,
            volume_type_ids=[fake.VOLUME_TYPE_ID],
            group_type_id=fake.GROUP_TYPE_ID,
            host=CONF.host)
        volume3 = tests_utils.create_volume(
            self.context,
            group_id=group3.id,
            source_volid=volume_id,
            status='available',
            host=group3.host,
            volume_type_id=fake.VOLUME_TYPE_ID)
        self.volume.create_volume(self.context, volume3.id, volume=volume3)
        self.volume.create_group_from_src(
            self.context, group3, source_group=group)

        grp3 = objects.Group.get_by_id(self.context, group3.id)

        self.assertEqual(fields.GroupStatus.AVAILABLE, grp3.status)
        self.assertEqual(group3.id, grp3.id)
        self.assertEqual(group.id, grp3.source_group_id)
        self.assertIsNone(grp3.group_snapshot_id)

        self.volume.delete_group_snapshot(self.context, group_snapshot)
        self.volume.delete_group(self.context, group)

    def test_sort_snapshots(self):
        vol1 = {'id': fake.VOLUME_ID, 'name': 'volume 1',
                'snapshot_id': fake.SNAPSHOT_ID,
                'group_id': fake.GROUP_ID}
        vol2 = {'id': fake.VOLUME2_ID, 'name': 'volume 2',
                'snapshot_id': fake.SNAPSHOT2_ID,
                'group_id': fake.GROUP_ID}
        vol3 = {'id': fake.VOLUME3_ID, 'name': 'volume 3',
                'snapshot_id': fake.SNAPSHOT3_ID,
                'group_id': fake.GROUP_ID}
        snp1 = {'id': fake.SNAPSHOT_ID, 'name': 'snap 1',
                'group_snapshot_id': fake.GROUP_ID}
        snp2 = {'id': fake.SNAPSHOT2_ID, 'name': 'snap 2',
                'group_snapshot_id': fake.GROUP_ID}
        snp3 = {'id': fake.SNAPSHOT3_ID, 'name': 'snap 3',
                'group_snapshot_id': fake.GROUP_ID}
        snp1_obj = fake_snapshot.fake_snapshot_obj(self.context, **snp1)
        snp2_obj = fake_snapshot.fake_snapshot_obj(self.context, **snp2)
        snp3_obj = fake_snapshot.fake_snapshot_obj(self.context, **snp3)
        volumes = []
        snapshots = []
        volumes.append(vol1)
        volumes.append(vol2)
        volumes.append(vol3)
        snapshots.append(snp2_obj)
        snapshots.append(snp3_obj)
        snapshots.append(snp1_obj)
        i = 0
        for vol in volumes:
            snap = snapshots[i]
            i += 1
            self.assertNotEqual(vol['snapshot_id'], snap.id)
        sorted_snaps = self.volume._sort_snapshots(volumes, snapshots)
        i = 0
        for vol in volumes:
            snap = sorted_snaps[i]
            i += 1
            self.assertEqual(vol['snapshot_id'], snap.id)

        snapshots[2]['id'] = fake.WILL_NOT_BE_FOUND_ID
        self.assertRaises(exception.SnapshotNotFound,
                          self.volume._sort_snapshots,
                          volumes, snapshots)

        self.assertRaises(exception.InvalidInput,
                          self.volume._sort_snapshots,
                          volumes, [])

    def test_sort_source_vols(self):
        vol1 = {'id': '1', 'name': 'volume 1',
                'source_volid': '1',
                'group_id': '2'}
        vol2 = {'id': '2', 'name': 'volume 2',
                'source_volid': '2',
                'group_id': '2'}
        vol3 = {'id': '3', 'name': 'volume 3',
                'source_volid': '3',
                'group_id': '2'}
        src_vol1 = {'id': '1', 'name': 'source vol 1',
                    'group_id': '1'}
        src_vol2 = {'id': '2', 'name': 'source vol 2',
                    'group_id': '1'}
        src_vol3 = {'id': '3', 'name': 'source vol 3',
                    'group_id': '1'}
        volumes = []
        src_vols = []
        volumes.append(vol1)
        volumes.append(vol2)
        volumes.append(vol3)
        src_vols.append(src_vol2)
        src_vols.append(src_vol3)
        src_vols.append(src_vol1)
        i = 0
        for vol in volumes:
            src_vol = src_vols[i]
            i += 1
            self.assertNotEqual(vol['source_volid'], src_vol['id'])
        sorted_src_vols = self.volume._sort_source_vols(volumes, src_vols)
        i = 0
        for vol in volumes:
            src_vol = sorted_src_vols[i]
            i += 1
            self.assertEqual(vol['source_volid'], src_vol['id'])

        src_vols[2]['id'] = '9999'
        self.assertRaises(exception.VolumeNotFound,
                          self.volume._sort_source_vols,
                          volumes, src_vols)

        self.assertRaises(exception.InvalidInput,
                          self.volume._sort_source_vols,
                          volumes, [])

    def _create_group_snapshot(self, group_id, volume_ids, size='0'):
        """Create a group_snapshot object."""
        grpsnap = objects.GroupSnapshot(self.context)
        grpsnap.user_id = fake.USER_ID
        grpsnap.project_id = fake.PROJECT_ID
        grpsnap.group_id = group_id
        grpsnap.status = fields.GroupStatus.CREATING
        grpsnap.create()

        # Create snapshot list
        for volume_id in volume_ids:
            snaps = []
            snap = objects.Snapshot(context.get_admin_context())
            snap.volume_size = size
            snap.user_id = fake.USER_ID
            snap.project_id = fake.PROJECT_ID
            snap.volume_id = volume_id
            snap.status = fields.SnapshotStatus.AVAILABLE
            snap.group_snapshot_id = grpsnap.id
            snap.create()
            snaps.append(snap)

        return grpsnap, snaps

    @mock.patch('cinder.tests.unit.fake_notifier.FakeNotifier._notify')
    @mock.patch('cinder.volume.driver.VolumeDriver.create_group',
                autospec=True,
                return_value={'status': 'available'})
    @mock.patch('cinder.volume.driver.VolumeDriver.delete_group',
                autospec=True,
                return_value=({'status': 'deleted'}, []))
    @mock.patch('cinder.volume.driver.VolumeDriver.create_group_snapshot',
                autospec=True,
                return_value=({'status': 'available'}, []))
    @mock.patch('cinder.volume.driver.VolumeDriver.delete_group_snapshot',
                autospec=True,
                return_value=({'status': 'deleted'}, []))
    def test_create_delete_group_snapshot(self,
                                          mock_del_grpsnap,
                                          mock_create_grpsnap,
                                          mock_del_grp,
                                          _mock_create_grp,
                                          mock_notify):
        """Test group_snapshot can be created and deleted."""
        group = tests_utils.create_group(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            volume_type_ids=[fake.VOLUME_TYPE_ID],
            group_type_id=fake.GROUP_TYPE_ID,
            host=CONF.host)
        volume = tests_utils.create_volume(
            self.context,
            group_id=group.id,
            host=group.host,
            volume_type_id=fake.VOLUME_TYPE_ID)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)

        self.assert_notify_called(mock_notify,
                                  (['INFO', 'volume.create.start'],
                                   ['INFO', 'volume.create.end']))

        group_snapshot_returns = self._create_group_snapshot(group.id,
                                                             [volume_id])
        group_snapshot = group_snapshot_returns[0]
        self.volume.create_group_snapshot(self.context, group_snapshot)
        self.assertEqual(group_snapshot.id,
                         objects.GroupSnapshot.get_by_id(
                             context.get_admin_context(),
                             group_snapshot.id).id)

        self.assert_notify_called(mock_notify,
                                  (['INFO', 'volume.create.start'],
                                   ['INFO', 'volume.create.end'],
                                   ['INFO', 'group_snapshot.create.start'],
                                   ['INFO', 'snapshot.create.start'],
                                   ['INFO', 'group_snapshot.create.end'],
                                   ['INFO', 'snapshot.create.end']))

        self.volume.delete_group_snapshot(self.context, group_snapshot)

        self.assert_notify_called(mock_notify,
                                  (['INFO', 'volume.create.start'],
                                   ['INFO', 'volume.create.end'],
                                   ['INFO', 'group_snapshot.create.start'],
                                   ['INFO', 'snapshot.create.start'],
                                   ['INFO', 'group_snapshot.create.end'],
                                   ['INFO', 'snapshot.create.end'],
                                   ['INFO', 'group_snapshot.delete.start'],
                                   ['INFO', 'snapshot.delete.start'],
                                   ['INFO', 'group_snapshot.delete.end'],
                                   ['INFO', 'snapshot.delete.end']))

        grpsnap = objects.GroupSnapshot.get_by_id(
            context.get_admin_context(read_deleted='yes'),
            group_snapshot.id)
        self.assertEqual('deleted', grpsnap.status)
        self.assertRaises(exception.NotFound,
                          objects.GroupSnapshot.get_by_id,
                          self.context,
                          group_snapshot.id)

        self.volume.delete_group(self.context, group)

        self.assertTrue(mock_create_grpsnap.called)
        self.assertTrue(mock_del_grpsnap.called)
        self.assertTrue(mock_del_grp.called)

    @mock.patch('cinder.volume.driver.VolumeDriver.create_group',
                return_value={'status': 'available'})
    @mock.patch('cinder.volume.driver.VolumeDriver.delete_group',
                return_value=({'status': 'deleted'}, []))
    def test_delete_group_correct_host(self,
                                       mock_del_grp,
                                       _mock_create_grp):
        """Test group can be deleted.

        Test group can be deleted when volumes are on
        the correct volume node.
        """
        group = tests_utils.create_group(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            volume_type_ids=[fake.VOLUME_TYPE_ID],
            group_type_id=fake.GROUP_TYPE_ID)
        volume = tests_utils.create_volume(
            self.context,
            group_id=group.id,
            host='host1@backend1#pool1',
            status='creating',
            volume_type_id=fake.VOLUME_TYPE_ID,
            size=1)
        self.volume.host = 'host1@backend1'
        self.volume.create_volume(self.context, volume.id, volume=volume)

        self.volume.delete_group(self.context, group)
        grp = objects.Group.get_by_id(
            context.get_admin_context(read_deleted='yes'),
            group.id)
        self.assertEqual(fields.GroupStatus.DELETED, grp.status)
        self.assertRaises(exception.NotFound,
                          objects.Group.get_by_id,
                          self.context,
                          group.id)

        self.assertTrue(mock_del_grp.called)

    @mock.patch('cinder.volume.driver.VolumeDriver.create_group',
                return_value={'status': 'available'})
    def test_delete_group_wrong_host(self, *_mock_create_grp):
        """Test group cannot be deleted.

        Test group cannot be deleted when volumes in the
        group are not local to the volume node.
        """
        group = tests_utils.create_group(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            volume_type_ids=[fake.VOLUME_TYPE_ID],
            group_type_id=fake.GROUP_TYPE_ID)
        volume = tests_utils.create_volume(
            self.context,
            group_id=group.id,
            host='host1@backend1#pool1',
            status='creating',
            volume_type_id=fake.VOLUME_TYPE_ID,
            size=1)
        self.volume.host = 'host1@backend2'
        self.volume.create_volume(self.context, volume.id, volume=volume)

        self.assertRaises(exception.InvalidVolume,
                          self.volume.delete_group,
                          self.context,
                          group)
        grp = objects.Group.get_by_id(self.context, group.id)
        # Group is not deleted
        self.assertEqual(fields.GroupStatus.AVAILABLE, grp.status)

    def test_create_volume_with_group_invalid_type(self):
        """Test volume creation with group & invalid volume type."""
        vol_type = db.volume_type_create(
            context.get_admin_context(),
            dict(name=conf_fixture.def_vol_type, extra_specs={})
        )
        db_vol_type = db.volume_type_get(context.get_admin_context(),
                                         vol_type.id)

        grp = tests_utils.create_group(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            status=fields.GroupStatus.AVAILABLE,
            volume_type_ids=[db_vol_type['id']],
            group_type_id=fake.GROUP_TYPE_ID,
            host=CONF.host)

        fake_type = {
            'id': '9999',
            'name': 'fake',
        }

        # Volume type must be provided when creating a volume in a
        # group.
        self.assertRaises(exception.InvalidInput,
                          self.volume_api.create,
                          self.context, 1, 'vol1', 'volume 1',
                          group=grp)

        # Volume type must be valid.
        self.assertRaises(exception.InvalidInput,
                          self.volume_api.create,
                          self.context, 1, 'vol1', 'volume 1',
                          volume_type=fake_type,
                          group=grp)

    @mock.patch('cinder.volume.driver.VolumeDriver.create_group_snapshot',
                autospec=True,
                return_value=({'status': 'available'}, []))
    def test_create_group_snapshot_with_bootable_volumes(self,
                                                         mock_create_grpsnap):
        """Test group_snapshot can be created and deleted."""
        group = tests_utils.create_group(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            volume_type_ids=[fake.VOLUME_TYPE_ID],
            group_type_id=fake.GROUP_TYPE_ID,
            host=CONF.host)
        volume = tests_utils.create_volume(
            self.context,
            group_id=group.id,
            host=group.host,
            volume_type_id=fake.VOLUME_TYPE_ID)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)
        # Create a bootable volume
        bootable_vol_params = {'status': 'creating', 'host': CONF.host,
                               'size': 1, 'bootable': True}
        bootable_vol = tests_utils.create_volume(self.context,
                                                 group_id=group.id,
                                                 **bootable_vol_params)
        # Create a common volume
        bootable_vol_id = bootable_vol['id']
        self.volume.create_volume(self.context, bootable_vol_id)

        volume_ids = [volume_id, bootable_vol_id]
        group_snapshot_returns = self._create_group_snapshot(group.id,
                                                             volume_ids)
        group_snapshot = group_snapshot_returns[0]
        self.volume.create_group_snapshot(self.context, group_snapshot)
        self.assertEqual(group_snapshot.id,
                         objects.GroupSnapshot.get_by_id(
                             context.get_admin_context(),
                             group_snapshot.id).id)
        self.assertTrue(mock_create_grpsnap.called)
