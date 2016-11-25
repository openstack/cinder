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

import cinder.consistencygroup
from cinder import context
from cinder import db
from cinder import exception
from cinder import objects
from cinder.objects import fields
from cinder import quota
from cinder.tests.unit import conf_fixture
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import utils as tests_utils
from cinder.tests.unit import volume as base
import cinder.volume
from cinder.volume import driver
from cinder.volume import utils as volutils

CGQUOTAS = quota.CGQUOTAS
CONF = cfg.CONF


@ddt.ddt
class ConsistencyGroupTestCase(base.BaseVolumeTestCase):
    def test_delete_volume_in_consistency_group(self):
        """Test deleting a volume that's tied to a consistency group fails."""
        consistencygroup_id = fake.CONSISTENCY_GROUP_ID
        volume_api = cinder.volume.api.API()
        self.volume_params.update({'status': 'available',
                                   'consistencygroup_id': consistencygroup_id})
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        self.assertRaises(exception.InvalidVolume,
                          volume_api.delete, self.context, volume)

    @mock.patch.object(CGQUOTAS, "reserve",
                       return_value=["RESERVATION"])
    @mock.patch.object(CGQUOTAS, "commit")
    @mock.patch.object(CGQUOTAS, "rollback")
    @mock.patch.object(driver.VolumeDriver,
                       "delete_consistencygroup",
                       return_value=({'status': (
                           fields.ConsistencyGroupStatus.DELETED)}, []))
    def test_create_delete_consistencygroup(self, fake_delete_cg,
                                            fake_rollback,
                                            fake_commit, fake_reserve):
        """Test consistencygroup can be created and deleted."""

        def fake_driver_create_cg(context, group):
            """Make sure that the pool is part of the host."""
            self.assertIn('host', group)
            host = group.host
            pool = volutils.extract_host(host, level='pool')
            self.assertEqual('fakepool', pool)
            return {'status': 'available'}

        self.mock_object(self.volume.driver, 'create_consistencygroup',
                         fake_driver_create_cg)

        group = tests_utils.create_consistencygroup(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            volume_type='type1,type2',
            host='fakehost@fakedrv#fakepool')
        group = objects.ConsistencyGroup.get_by_id(self.context, group.id)
        self.assertEqual(0, len(self.notifier.notifications),
                         self.notifier.notifications)
        self.volume.create_consistencygroup(self.context, group)
        self.assertEqual(2, len(self.notifier.notifications),
                         self.notifier.notifications)
        msg = self.notifier.notifications[0]
        self.assertEqual('consistencygroup.create.start', msg['event_type'])
        expected = {
            'status': fields.ConsistencyGroupStatus.AVAILABLE,
            'name': 'test_cg',
            'availability_zone': 'nova',
            'tenant_id': self.context.project_id,
            'created_at': mock.ANY,
            'user_id': fake.USER_ID,
            'consistencygroup_id': group.id
        }
        self.assertDictEqual(expected, msg['payload'])
        msg = self.notifier.notifications[1]
        self.assertEqual('consistencygroup.create.end', msg['event_type'])
        self.assertDictEqual(expected, msg['payload'])
        self.assertEqual(
            group.id,
            objects.ConsistencyGroup.get_by_id(context.get_admin_context(),
                                               group.id).id)

        self.volume.delete_consistencygroup(self.context, group)
        cg = objects.ConsistencyGroup.get_by_id(
            context.get_admin_context(read_deleted='yes'), group.id)
        self.assertEqual(fields.ConsistencyGroupStatus.DELETED, cg.status)
        self.assertEqual(4, len(self.notifier.notifications),
                         self.notifier.notifications)
        msg = self.notifier.notifications[2]
        self.assertEqual('consistencygroup.delete.start', msg['event_type'])
        self.assertDictEqual(expected, msg['payload'])
        msg = self.notifier.notifications[3]
        self.assertEqual('consistencygroup.delete.end', msg['event_type'])
        expected['status'] = fields.ConsistencyGroupStatus.DELETED
        self.assertDictEqual(expected, msg['payload'])
        self.assertRaises(exception.NotFound,
                          objects.ConsistencyGroup.get_by_id,
                          self.context,
                          group.id)

    @mock.patch.object(CGQUOTAS, "reserve",
                       return_value=["RESERVATION"])
    @mock.patch.object(CGQUOTAS, "commit")
    @mock.patch.object(CGQUOTAS, "rollback")
    @mock.patch.object(driver.VolumeDriver,
                       "create_consistencygroup",
                       return_value={'status': 'available'})
    @mock.patch.object(driver.VolumeDriver,
                       "update_consistencygroup")
    def test_update_consistencygroup(self, fake_update_cg,
                                     fake_create_cg, fake_rollback,
                                     fake_commit, fake_reserve):
        """Test consistencygroup can be updated."""
        group = tests_utils.create_consistencygroup(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            volume_type='type1,type2')
        self.volume.create_consistencygroup(self.context, group)

        volume = tests_utils.create_volume(
            self.context,
            consistencygroup_id=group.id,
            **self.volume_params)
        self.volume.create_volume(self.context, volume)

        volume2 = tests_utils.create_volume(
            self.context,
            consistencygroup_id=None,
            **self.volume_params)
        self.volume.create_volume(self.context, volume2)

        fake_update_cg.return_value = (
            {'status': fields.ConsistencyGroupStatus.AVAILABLE},
            [{'id': volume2.id, 'status': 'available'}],
            [{'id': volume.id, 'status': 'available'}])

        self.volume.update_consistencygroup(self.context, group,
                                            add_volumes=volume2.id,
                                            remove_volumes=volume.id)
        cg = objects.ConsistencyGroup.get_by_id(self.context, group.id)
        expected = {
            'status': fields.ConsistencyGroupStatus.AVAILABLE,
            'name': 'test_cg',
            'availability_zone': 'nova',
            'tenant_id': self.context.project_id,
            'created_at': mock.ANY,
            'user_id': fake.USER_ID,
            'consistencygroup_id': group.id
        }
        self.assertEqual(fields.ConsistencyGroupStatus.AVAILABLE, cg.status)
        self.assertEqual(10, len(self.notifier.notifications),
                         self.notifier.notifications)
        msg = self.notifier.notifications[6]
        self.assertEqual('consistencygroup.update.start', msg['event_type'])
        self.assertDictEqual(expected, msg['payload'])
        msg = self.notifier.notifications[8]
        self.assertEqual('consistencygroup.update.end', msg['event_type'])
        self.assertDictEqual(expected, msg['payload'])
        cgvolumes = db.volume_get_all_by_group(self.context, group.id)
        cgvol_ids = [cgvol['id'] for cgvol in cgvolumes]
        # Verify volume is removed.
        self.assertNotIn(volume.id, cgvol_ids)
        # Verify volume is added.
        self.assertIn(volume2.id, cgvol_ids)

        self.volume_params['status'] = 'wrong-status'
        volume3 = tests_utils.create_volume(
            self.context,
            consistencygroup_id=None,
            **self.volume_params)
        volume_id3 = volume3['id']

        volume_get_orig = self.volume.db.volume_get
        self.volume.db.volume_get = mock.Mock(
            return_value={'status': 'wrong_status',
                          'id': volume_id3})
        # Try to add a volume in wrong status
        self.assertRaises(exception.InvalidVolume,
                          self.volume.update_consistencygroup,
                          self.context,
                          group,
                          add_volumes=volume_id3,
                          remove_volumes=None)
        self.volume.db.volume_get.reset_mock()
        self.volume.db.volume_get = volume_get_orig

    def test_update_consistencygroup_volume_not_found(self):
        group = tests_utils.create_consistencygroup(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            volume_type='type1,type2')
        self.assertRaises(exception.VolumeNotFound,
                          self.volume.update_consistencygroup,
                          self.context,
                          group,
                          fake.VOLUME_ID)
        self.assertRaises(exception.VolumeNotFound,
                          self.volume.update_consistencygroup,
                          self.context,
                          group,
                          None,
                          fake.VOLUME_ID)

    @mock.patch.object(driver.VolumeDriver,
                       "create_consistencygroup",
                       return_value={'status': 'available'})
    @mock.patch.object(driver.VolumeDriver,
                       "delete_consistencygroup",
                       return_value=({'status': 'deleted'}, []))
    @mock.patch.object(driver.VolumeDriver,
                       "create_cgsnapshot",
                       return_value={'status': 'available'})
    @mock.patch.object(driver.VolumeDriver,
                       "delete_cgsnapshot",
                       return_value=({'status': 'deleted'}, []))
    @mock.patch.object(driver.VolumeDriver,
                       "create_consistencygroup_from_src",
                       return_value=(None, None))
    @mock.patch('cinder.volume.drivers.lvm.LVMVolumeDriver.'
                'create_volume_from_snapshot')
    @mock.patch('cinder.volume.drivers.lvm.LVMVolumeDriver.'
                'create_cloned_volume')
    def test_create_consistencygroup_from_src(self,
                                              mock_create_cloned_vol,
                                              mock_create_vol_from_snap,
                                              mock_create_from_src,
                                              mock_delete_cgsnap,
                                              mock_create_cgsnap,
                                              mock_delete_cg,
                                              mock_create_cg):
        """Test consistencygroup can be created and deleted."""
        group = tests_utils.create_consistencygroup(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            volume_type='type1,type2',
            status=fields.ConsistencyGroupStatus.AVAILABLE)
        volume = tests_utils.create_volume(
            self.context,
            consistencygroup_id=group.id,
            status='available',
            host=CONF.host,
            size=1)
        volume_id = volume['id']
        cgsnapshot_returns = self._create_cgsnapshot(group.id, [volume_id])
        cgsnapshot = cgsnapshot_returns[0]
        snapshot_id = cgsnapshot_returns[1][0]['id']

        # Create CG from source CG snapshot.
        group2 = tests_utils.create_consistencygroup(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            volume_type='type1,type2',
            cgsnapshot_id=cgsnapshot.id)
        group2 = objects.ConsistencyGroup.get_by_id(self.context, group2.id)
        volume2 = tests_utils.create_volume(
            self.context,
            consistencygroup_id=group2.id,
            snapshot_id=snapshot_id,
            **self.volume_params)
        self.volume.create_volume(self.context, volume2)
        self.volume.create_consistencygroup_from_src(
            self.context, group2, cgsnapshot=cgsnapshot)
        cg2 = objects.ConsistencyGroup.get_by_id(self.context, group2.id)
        expected = {
            'status': fields.ConsistencyGroupStatus.AVAILABLE,
            'name': 'test_cg',
            'availability_zone': 'nova',
            'tenant_id': self.context.project_id,
            'created_at': mock.ANY,
            'user_id': fake.USER_ID,
            'consistencygroup_id': group2.id,
        }
        self.assertEqual(fields.ConsistencyGroupStatus.AVAILABLE, cg2.status)
        self.assertEqual(group2.id, cg2['id'])
        self.assertEqual(cgsnapshot.id, cg2['cgsnapshot_id'])
        self.assertIsNone(cg2['source_cgid'])

        msg = self.notifier.notifications[2]
        self.assertEqual('consistencygroup.create.start', msg['event_type'])
        self.assertDictEqual(expected, msg['payload'])
        msg = self.notifier.notifications[4]
        self.assertEqual('consistencygroup.create.end', msg['event_type'])
        self.assertDictEqual(expected, msg['payload'])

        if len(self.notifier.notifications) > 6:
            self.assertFalse(self.notifier.notifications[6],
                             self.notifier.notifications)
        self.assertEqual(6, len(self.notifier.notifications),
                         self.notifier.notifications)

        self.volume.delete_consistencygroup(self.context, group2)

        if len(self.notifier.notifications) > 10:
            self.assertFalse(self.notifier.notifications[10],
                             self.notifier.notifications)
        self.assertEqual(10, len(self.notifier.notifications),
                         self.notifier.notifications)

        msg = self.notifier.notifications[6]
        self.assertEqual('consistencygroup.delete.start', msg['event_type'])
        expected['status'] = fields.ConsistencyGroupStatus.AVAILABLE
        self.assertDictEqual(expected, msg['payload'])
        msg = self.notifier.notifications[8]
        self.assertEqual('consistencygroup.delete.end', msg['event_type'])
        expected['status'] = fields.ConsistencyGroupStatus.DELETED
        self.assertDictEqual(expected, msg['payload'])

        cg2 = objects.ConsistencyGroup.get_by_id(
            context.get_admin_context(read_deleted='yes'), group2.id)
        self.assertEqual(fields.ConsistencyGroupStatus.DELETED, cg2.status)
        self.assertRaises(exception.NotFound,
                          objects.ConsistencyGroup.get_by_id,
                          self.context,
                          group2.id)

        # Create CG from source CG.
        group3 = tests_utils.create_consistencygroup(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            volume_type='type1,type2',
            source_cgid=group.id)
        volume3 = tests_utils.create_volume(
            self.context,
            consistencygroup_id=group3.id,
            source_volid=volume_id,
            **self.volume_params)
        self.volume.create_volume(self.context, volume3)
        self.volume.create_consistencygroup_from_src(
            self.context, group3, source_cg=group)

        cg3 = objects.ConsistencyGroup.get_by_id(self.context, group3.id)

        self.assertEqual(fields.ConsistencyGroupStatus.AVAILABLE, cg3.status)
        self.assertEqual(group3.id, cg3.id)
        self.assertEqual(group.id, cg3.source_cgid)
        self.assertIsNone(cg3.cgsnapshot_id)

        self.volume.delete_cgsnapshot(self.context, cgsnapshot)

        self.volume.delete_consistencygroup(self.context, group)

    def test_create_consistencygroup_from_src_frozen(self):
        service = tests_utils.create_service(self.context, {'frozen': True})
        cg = tests_utils.create_consistencygroup(self.context,
                                                 host=service.host)
        cg_api = cinder.consistencygroup.api.API()
        self.assertRaises(exception.InvalidInput,
                          cg_api.create_from_src,
                          self.context, 'cg', 'desc', cgsnapshot_id=None,
                          source_cgid=cg.id)

    def test_delete_consistencygroup_frozen(self):
        service = tests_utils.create_service(self.context, {'frozen': True})
        cg = tests_utils.create_consistencygroup(self.context,
                                                 host=service.host)
        cg_api = cinder.consistencygroup.api.API()
        self.assertRaises(exception.InvalidInput,
                          cg_api.delete, self.context, cg)

    def test_create_cgsnapshot_frozen(self):
        service = tests_utils.create_service(self.context, {'frozen': True})
        cg = tests_utils.create_consistencygroup(self.context,
                                                 host=service.host)
        cg_api = cinder.consistencygroup.api.API()
        self.assertRaises(exception.InvalidInput,
                          cg_api.create_cgsnapshot,
                          self.context, cg, 'cg', 'desc')

    def test_delete_cgsnapshot_frozen(self):
        service = tests_utils.create_service(self.context, {'frozen': True})
        cg = tests_utils.create_consistencygroup(self.context,
                                                 host=service.host)
        cgsnap = tests_utils.create_cgsnapshot(self.context, cg.id)
        cg_api = cinder.consistencygroup.api.API()
        self.assertRaises(exception.InvalidInput,
                          cg_api.delete_cgsnapshot,
                          self.context, cgsnap)

    def test_sort_snapshots(self):
        vol1 = {'id': fake.VOLUME_ID, 'name': 'volume 1',
                'snapshot_id': fake.SNAPSHOT_ID,
                'consistencygroup_id': fake.CONSISTENCY_GROUP_ID}
        vol2 = {'id': fake.VOLUME2_ID, 'name': 'volume 2',
                'snapshot_id': fake.SNAPSHOT2_ID,
                'consistencygroup_id': fake.CONSISTENCY_GROUP_ID}
        vol3 = {'id': fake.VOLUME3_ID, 'name': 'volume 3',
                'snapshot_id': fake.SNAPSHOT3_ID,
                'consistencygroup_id': fake.CONSISTENCY_GROUP_ID}
        snp1 = {'id': fake.SNAPSHOT_ID, 'name': 'snap 1',
                'cgsnapshot_id': fake.CONSISTENCY_GROUP_ID}
        snp2 = {'id': fake.SNAPSHOT2_ID, 'name': 'snap 2',
                'cgsnapshot_id': fake.CONSISTENCY_GROUP_ID}
        snp3 = {'id': fake.SNAPSHOT3_ID, 'name': 'snap 3',
                'cgsnapshot_id': fake.CONSISTENCY_GROUP_ID}
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
                'consistencygroup_id': '2'}
        vol2 = {'id': '2', 'name': 'volume 2',
                'source_volid': '2',
                'consistencygroup_id': '2'}
        vol3 = {'id': '3', 'name': 'volume 3',
                'source_volid': '3',
                'consistencygroup_id': '2'}
        src_vol1 = {'id': '1', 'name': 'source vol 1',
                    'consistencygroup_id': '1'}
        src_vol2 = {'id': '2', 'name': 'source vol 2',
                    'consistencygroup_id': '1'}
        src_vol3 = {'id': '3', 'name': 'source vol 3',
                    'consistencygroup_id': '1'}
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

    def _create_cgsnapshot(self, group_id, volume_ids, size='0'):
        """Create a cgsnapshot object."""
        cgsnap = objects.CGSnapshot(self.context)
        cgsnap.user_id = fake.USER_ID
        cgsnap.project_id = fake.PROJECT_ID
        cgsnap.consistencygroup_id = group_id
        cgsnap.status = "creating"
        cgsnap.create()

        # Create snapshot list
        for volume_id in volume_ids:
            snaps = []
            snap = objects.Snapshot(context.get_admin_context())
            snap.volume_size = size
            snap.user_id = fake.USER_ID
            snap.project_id = fake.PROJECT_ID
            snap.volume_id = volume_id
            snap.status = "available"
            snap.cgsnapshot_id = cgsnap.id
            snap.create()
            snaps.append(snap)

        return cgsnap, snaps

    @ddt.data((CONF.host, None), (CONF.host + 'fake', 'mycluster'))
    @ddt.unpack
    @mock.patch('cinder.tests.unit.fake_notifier.FakeNotifier._notify')
    @mock.patch('cinder.volume.driver.VolumeDriver.create_consistencygroup',
                autospec=True,
                return_value={'status': 'available'})
    @mock.patch('cinder.volume.driver.VolumeDriver.delete_consistencygroup',
                autospec=True,
                return_value=({'status': 'deleted'}, []))
    @mock.patch('cinder.volume.driver.VolumeDriver.create_cgsnapshot',
                autospec=True,
                return_value=({'status': 'available'}, []))
    @mock.patch('cinder.volume.driver.VolumeDriver.delete_cgsnapshot',
                autospec=True,
                return_value=({'status': 'deleted'}, []))
    def test_create_delete_cgsnapshot(self, host, cluster,
                                      mock_del_cgsnap, mock_create_cgsnap,
                                      mock_del_cg, _mock_create_cg,
                                      mock_notify):
        """Test cgsnapshot can be created and deleted."""

        self.volume.cluster = cluster
        group = tests_utils.create_consistencygroup(
            self.context,
            host=host,
            cluster_name=cluster,
            availability_zone=CONF.storage_availability_zone,
            volume_type='type1,type2')
        self.volume_params['host'] = host
        volume = tests_utils.create_volume(
            self.context,
            cluster_name=cluster,
            consistencygroup_id=group.id,
            **self.volume_params)
        self.volume.create_volume(self.context, volume)

        self.assert_notify_called(mock_notify,
                                  (['INFO', 'volume.create.start'],
                                   ['INFO', 'volume.create.end']))

        cgsnapshot_returns = self._create_cgsnapshot(group.id, [volume.id])
        cgsnapshot = cgsnapshot_returns[0]
        self.volume.create_cgsnapshot(self.context, cgsnapshot)
        self.assertEqual(cgsnapshot.id,
                         objects.CGSnapshot.get_by_id(
                             context.get_admin_context(),
                             cgsnapshot.id).id)

        self.assert_notify_called(mock_notify,
                                  (['INFO', 'volume.create.start'],
                                   ['INFO', 'volume.create.end'],
                                   ['INFO', 'cgsnapshot.create.start'],
                                   ['INFO', 'snapshot.create.start'],
                                   ['INFO', 'cgsnapshot.create.end'],
                                   ['INFO', 'snapshot.create.end']))

        self.volume.delete_cgsnapshot(self.context, cgsnapshot)

        self.assert_notify_called(mock_notify,
                                  (['INFO', 'volume.create.start'],
                                   ['INFO', 'volume.create.end'],
                                   ['INFO', 'cgsnapshot.create.start'],
                                   ['INFO', 'snapshot.create.start'],
                                   ['INFO', 'cgsnapshot.create.end'],
                                   ['INFO', 'snapshot.create.end'],
                                   ['INFO', 'cgsnapshot.delete.start'],
                                   ['INFO', 'snapshot.delete.start'],
                                   ['INFO', 'cgsnapshot.delete.end'],
                                   ['INFO', 'snapshot.delete.end']))

        cgsnap = objects.CGSnapshot.get_by_id(
            context.get_admin_context(read_deleted='yes'),
            cgsnapshot.id)
        self.assertEqual('deleted', cgsnap.status)
        self.assertRaises(exception.NotFound,
                          objects.CGSnapshot.get_by_id,
                          self.context,
                          cgsnapshot.id)

        self.volume.delete_consistencygroup(self.context, group)

        self.assertTrue(mock_create_cgsnap.called)
        self.assertTrue(mock_del_cgsnap.called)
        self.assertTrue(mock_del_cg.called)

    @mock.patch('cinder.volume.driver.VolumeDriver.create_consistencygroup',
                return_value={'status': 'available'})
    @mock.patch('cinder.volume.driver.VolumeDriver.delete_consistencygroup',
                return_value=({'status': 'deleted'}, []))
    def test_delete_consistencygroup_correct_host(self,
                                                  mock_del_cg,
                                                  _mock_create_cg):
        """Test consistencygroup can be deleted.

        Test consistencygroup can be deleted when volumes are on
        the correct volume node.
        """

        group = tests_utils.create_consistencygroup(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            volume_type='type1,type2')

        volume = tests_utils.create_volume(
            self.context,
            consistencygroup_id=group.id,
            host='host1@backend1#pool1',
            status='creating',
            size=1)
        self.volume.host = 'host1@backend1'
        self.volume.create_volume(self.context, volume)

        self.volume.delete_consistencygroup(self.context, group)
        cg = objects.ConsistencyGroup.get_by_id(
            context.get_admin_context(read_deleted='yes'),
            group.id)
        self.assertEqual(fields.ConsistencyGroupStatus.DELETED, cg.status)
        self.assertRaises(exception.NotFound,
                          objects.ConsistencyGroup.get_by_id,
                          self.context,
                          group.id)

        self.assertTrue(mock_del_cg.called)

    @mock.patch('cinder.volume.driver.VolumeDriver.create_consistencygroup',
                mock.Mock(return_value={'status': 'available'}))
    @mock.patch('cinder.volume.driver.VolumeDriver.delete_consistencygroup',
                return_value=({'status': 'deleted'}, []))
    def test_delete_consistencygroup_cluster(self, mock_del_cg):
        """Test consistencygroup can be deleted.

        Test consistencygroup can be deleted when volumes are on
        the correct volume node.
        """
        cluster_name = 'cluster@backend1'
        self.volume.host = 'host2@backend1'
        self.volume.cluster = cluster_name
        group = tests_utils.create_consistencygroup(
            self.context,
            host=CONF.host + 'fake',
            cluster_name=cluster_name,
            availability_zone=CONF.storage_availability_zone,
            volume_type='type1,type2')

        volume = tests_utils.create_volume(
            self.context,
            consistencygroup_id=group.id,
            host='host1@backend1#pool1',
            cluster_name=cluster_name,
            status='creating',
            size=1)
        self.volume.create_volume(self.context, volume)

        self.volume.delete_consistencygroup(self.context, group)
        cg = objects.ConsistencyGroup.get_by_id(
            context.get_admin_context(read_deleted='yes'),
            group.id)
        self.assertEqual(fields.ConsistencyGroupStatus.DELETED, cg.status)
        self.assertRaises(exception.NotFound,
                          objects.ConsistencyGroup.get_by_id,
                          self.context,
                          group.id)

        self.assertTrue(mock_del_cg.called)

    @mock.patch('cinder.volume.driver.VolumeDriver.create_consistencygroup',
                return_value={'status': 'available'})
    def test_delete_consistencygroup_wrong_host(self, *_mock_create_cg):
        """Test consistencygroup cannot be deleted.

        Test consistencygroup cannot be deleted when volumes in the
        group are not local to the volume node.
        """

        group = tests_utils.create_consistencygroup(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            volume_type='type1,type2')

        volume = tests_utils.create_volume(
            self.context,
            consistencygroup_id=group.id,
            host='host1@backend1#pool1',
            status='creating',
            size=1)
        self.volume.host = 'host1@backend2'
        self.volume.create_volume(self.context, volume)

        self.assertRaises(exception.Invalid,
                          self.volume.delete_consistencygroup,
                          self.context,
                          group)
        cg = objects.ConsistencyGroup.get_by_id(self.context, group.id)
        # Group is not deleted
        self.assertEqual(fields.ConsistencyGroupStatus.AVAILABLE, cg.status)

    def test_create_volume_with_consistencygroup_invalid_type(self):
        """Test volume creation with ConsistencyGroup & invalid volume type."""
        vol_type = db.volume_type_create(
            context.get_admin_context(),
            dict(name=conf_fixture.def_vol_type, extra_specs={})
        )
        db_vol_type = db.volume_type_get(context.get_admin_context(),
                                         vol_type.id)
        cg = {
            'id': '1',
            'name': 'cg1',
            'volume_type_id': db_vol_type['id'],
        }
        fake_type = {
            'id': '9999',
            'name': 'fake',
        }
        vol_api = cinder.volume.api.API()

        # Volume type must be provided when creating a volume in a
        # consistency group.
        self.assertRaises(exception.InvalidInput,
                          vol_api.create,
                          self.context, 1, 'vol1', 'volume 1',
                          consistencygroup=cg)

        # Volume type must be valid.
        self.assertRaises(exception.InvalidInput,
                          vol_api.create,
                          self.context, 1, 'vol1', 'volume 1',
                          volume_type=fake_type,
                          consistencygroup=cg)

    @mock.patch('cinder.volume.driver.VolumeDriver.create_cgsnapshot',
                autospec=True,
                return_value=({'status': 'available'}, []))
    def test_create_cgsnapshot_with_bootable_volumes(self, mock_create_cgsnap):
        """Test cgsnapshot can be created and deleted."""

        group = tests_utils.create_consistencygroup(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            volume_type='type1,type2')
        volume = tests_utils.create_volume(
            self.context,
            consistencygroup_id=group.id,
            **self.volume_params)
        self.volume.create_volume(self.context, volume)
        # Create a bootable volume
        bootable_vol_params = {'status': 'creating', 'host': CONF.host,
                               'size': 1, 'bootable': True}
        bootable_vol = tests_utils.create_volume(self.context,
                                                 consistencygroup_id=group.id,
                                                 **bootable_vol_params)
        # Create a common volume
        self.volume.create_volume(self.context, bootable_vol)

        volume_ids = [volume.id, bootable_vol.id]
        cgsnapshot_returns = self._create_cgsnapshot(group.id, volume_ids)
        cgsnapshot = cgsnapshot_returns[0]
        self.volume.create_cgsnapshot(self.context, cgsnapshot)
        self.assertEqual(cgsnapshot.id,
                         objects.CGSnapshot.get_by_id(
                             context.get_admin_context(),
                             cgsnapshot.id).id)
        self.assertTrue(mock_create_cgsnap.called)
