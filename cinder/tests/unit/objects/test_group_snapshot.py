#    Copyright 2016 EMC Corporation
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

from unittest import mock

from oslo_utils import timeutils
import pytz

from cinder import exception
from cinder import objects
from cinder.objects import fields
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import objects as test_objects
from cinder.tests.unit.objects.test_group import fake_group

fake_group_snapshot = {
    'id': fake.GROUP_SNAPSHOT_ID,
    'user_id': fake.USER_ID,
    'project_id': fake.PROJECT_ID,
    'name': 'fake_name',
    'description': 'fake_description',
    'status': fields.GroupSnapshotStatus.CREATING,
    'group_id': fake.GROUP_ID,
}


class TestGroupSnapshot(test_objects.BaseObjectsTestCase):

    @mock.patch('cinder.db.sqlalchemy.api.group_snapshot_get',
                return_value=fake_group_snapshot)
    def test_get_by_id(self, group_snapshot_get):
        group_snapshot = objects.GroupSnapshot.get_by_id(
            self.context,
            fake.GROUP_SNAPSHOT_ID)
        self._compare(self, fake_group_snapshot, group_snapshot)

    @mock.patch('cinder.db.group_snapshot_create',
                return_value=fake_group_snapshot)
    def test_create(self, group_snapshot_create):
        fake_group_snap = fake_group_snapshot.copy()
        del fake_group_snap['id']
        group_snapshot = objects.GroupSnapshot(context=self.context,
                                               **fake_group_snap)
        group_snapshot.create()
        self._compare(self, fake_group_snapshot, group_snapshot)

    def test_create_with_id_except_exception(self):
        group_snapshot = objects.GroupSnapshot(
            context=self.context,
            **{'id': fake.GROUP_ID})
        self.assertRaises(exception.ObjectActionError, group_snapshot.create)

    @mock.patch('cinder.db.group_snapshot_update')
    def test_save(self, group_snapshot_update):
        group_snapshot = objects.GroupSnapshot._from_db_object(
            self.context, objects.GroupSnapshot(), fake_group_snapshot)
        group_snapshot.status = 'active'
        group_snapshot.save()
        group_snapshot_update.assert_called_once_with(self.context,
                                                      group_snapshot.id,
                                                      {'status': 'active'})

    @mock.patch('cinder.db.group_update',
                return_value=fake_group)
    @mock.patch('cinder.db.group_snapshot_update')
    def test_save_with_group(self, group_snapshot_update,
                             group_snapshot_cg_update):
        group = objects.Group._from_db_object(
            self.context, objects.Group(), fake_group)
        group_snapshot = objects.GroupSnapshot._from_db_object(
            self.context, objects.GroupSnapshot(), fake_group_snapshot)
        group_snapshot.name = 'foobar'
        group_snapshot.group = group
        self.assertEqual({'name': 'foobar',
                          'group': group},
                         group_snapshot.obj_get_changes())
        self.assertRaises(exception.ObjectActionError, group_snapshot.save)

    @mock.patch('oslo_utils.timeutils.utcnow', return_value=timeutils.utcnow())
    @mock.patch('cinder.db.sqlalchemy.api.group_snapshot_destroy')
    def test_destroy(self, group_snapshot_destroy, utcnow_mock):
        group_snapshot_destroy.return_value = {
            'status': fields.GroupSnapshotStatus.DELETED,
            'deleted': True,
            'deleted_at': utcnow_mock.return_value}
        group_snapshot = objects.GroupSnapshot(context=self.context,
                                               id=fake.GROUP_SNAPSHOT_ID)
        group_snapshot.destroy()
        self.assertTrue(group_snapshot_destroy.called)
        admin_context = group_snapshot_destroy.call_args[0][0]
        self.assertTrue(admin_context.is_admin)
        self.assertTrue(group_snapshot.deleted)
        self.assertEqual(fields.GroupSnapshotStatus.DELETED,
                         group_snapshot.status)
        self.assertEqual(utcnow_mock.return_value.replace(tzinfo=pytz.UTC),
                         group_snapshot.deleted_at)

    @mock.patch('cinder.objects.group.Group.get_by_id')
    @mock.patch(
        'cinder.objects.snapshot.SnapshotList.get_all_for_group_snapshot')
    def test_obj_load_attr(self, snapshotlist_get_for_cgs,
                           group_get_by_id):
        group_snapshot = objects.GroupSnapshot._from_db_object(
            self.context, objects.GroupSnapshot(), fake_group_snapshot)
        # Test group lazy-loaded field
        group = objects.Group(
            context=self.context, id=fake.GROUP_ID)
        group_get_by_id.return_value = group
        self.assertEqual(group, group_snapshot.group)
        group_get_by_id.assert_called_once_with(
            self.context, group_snapshot.group_id)
        # Test snapshots lazy-loaded field
        snapshots_objs = [objects.Snapshot(context=self.context, id=i)
                          for i in [fake.SNAPSHOT_ID, fake.SNAPSHOT2_ID,
                                    fake.SNAPSHOT3_ID]]
        snapshots = objects.SnapshotList(context=self.context,
                                         objects=snapshots_objs)
        snapshotlist_get_for_cgs.return_value = snapshots
        self.assertEqual(snapshots, group_snapshot.snapshots)
        snapshotlist_get_for_cgs.assert_called_once_with(
            self.context, group_snapshot.id)

    @mock.patch('cinder.db.sqlalchemy.api.group_snapshot_get')
    def test_refresh(self, group_snapshot_get):
        db_group_snapshot1 = fake_group_snapshot.copy()
        db_group_snapshot2 = db_group_snapshot1.copy()
        db_group_snapshot2['description'] = 'foobar'

        # On the second group_snapshot_get, return the GroupSnapshot with an
        # updated description
        group_snapshot_get.side_effect = [db_group_snapshot1,
                                          db_group_snapshot2]
        group_snapshot = objects.GroupSnapshot.get_by_id(
            self.context, fake.GROUP_SNAPSHOT_ID)
        self._compare(self, db_group_snapshot1, group_snapshot)

        # description was updated, so a GroupSnapshot refresh should have a new
        # value for that field
        group_snapshot.refresh()
        self._compare(self, db_group_snapshot2, group_snapshot)
        group_snapshot_get.assert_has_calls(
            [mock.call(self.context,
                       fake.GROUP_SNAPSHOT_ID),
             mock.call.__bool__(),
             mock.call(self.context,
                       fake.GROUP_SNAPSHOT_ID)])


class TestGroupSnapshotList(test_objects.BaseObjectsTestCase):
    @mock.patch('cinder.db.group_snapshot_get_all',
                return_value=[fake_group_snapshot])
    def test_get_all(self, group_snapshot_get_all):
        group_snapshots = objects.GroupSnapshotList.get_all(self.context)
        self.assertEqual(1, len(group_snapshots))
        TestGroupSnapshot._compare(self, fake_group_snapshot,
                                   group_snapshots[0])

    @mock.patch('cinder.db.group_snapshot_get_all_by_project',
                return_value=[fake_group_snapshot])
    def test_get_all_by_project(self, group_snapshot_get_all_by_project):
        group_snapshots = objects.GroupSnapshotList.get_all_by_project(
            self.context, self.project_id)
        self.assertEqual(1, len(group_snapshots))
        TestGroupSnapshot._compare(self, fake_group_snapshot,
                                   group_snapshots[0])

    @mock.patch('cinder.db.group_snapshot_get_all_by_group',
                return_value=[fake_group_snapshot])
    def test_get_all_by_group(self, group_snapshot_get_all_by_group):
        group_snapshots = objects.GroupSnapshotList.get_all_by_group(
            self.context, self.project_id)
        self.assertEqual(1, len(group_snapshots))
        TestGroupSnapshot._compare(self, fake_group_snapshot,
                                   group_snapshots[0])
