#    Copyright 2015 SimpliVity Corp.
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

from cinder.objects import snapshot as snapshot_obj
from cinder.objects import volume as volume_obj
from cinder.tests import fake_volume
from cinder.tests.objects import test_objects

fake_snapshot = {
    'id': '1',
    'volume_id': 'fake_id',
    'status': "creating",
    'progress': '0%',
    'volume_size': 1,
    'display_name': 'fake_name',
    'display_description': 'fake_description',
}


class TestSnapshot(test_objects._LocalTest):
    @staticmethod
    def _compare(test, db, obj):
        for field, value in db.items():
            test.assertEqual(db[field], obj[field])

    @mock.patch('cinder.db.snapshot_metadata_get', return_value={})
    @mock.patch('cinder.db.snapshot_get', return_value=fake_snapshot)
    def test_get_by_id(self, snapshot_get, snapshot_metadata_get):
        snapshot = snapshot_obj.Snapshot.get_by_id(self.context, 1)
        self._compare(self, fake_snapshot, snapshot)

    def test_reset_changes(self):
        snapshot = snapshot_obj.Snapshot()
        snapshot.metadata = {'key1': 'value1'}
        self.assertEqual({}, snapshot._orig_metadata)
        snapshot.obj_reset_changes(['metadata'])
        self.assertEqual({'key1': 'value1'}, snapshot._orig_metadata)

    @mock.patch('cinder.db.snapshot_create', return_value=fake_snapshot)
    def test_create(self, snapshot_create):
        snapshot = snapshot_obj.Snapshot(context=self.context)
        snapshot.create()
        self.assertEqual(fake_snapshot['id'], snapshot.id)
        self.assertEqual(fake_snapshot['volume_id'], snapshot.volume_id)

    @mock.patch('cinder.db.snapshot_create',
                return_value=dict(provider_id='1111-aaaa', **fake_snapshot))
    def test_create_with_provider_id(self, snapshot_create):
        snapshot = snapshot_obj.Snapshot(context=self.context)
        snapshot.create()
        self.assertEqual('1111-aaaa', snapshot.provider_id)

    @mock.patch('cinder.db.snapshot_update')
    def test_save(self, snapshot_update):
        snapshot = snapshot_obj.Snapshot._from_db_object(
            self.context, snapshot_obj.Snapshot(), fake_snapshot)
        snapshot.display_name = 'foobar'
        snapshot.save(self.context)
        snapshot_update.assert_called_once_with(self.context, snapshot.id,
                                                {'display_name': 'foobar'})

    @mock.patch('cinder.db.snapshot_metadata_update',
                return_value={'key1': 'value1'})
    @mock.patch('cinder.db.snapshot_update')
    def test_save_with_metadata(self, snapshot_update,
                                snapshot_metadata_update):
        snapshot = snapshot_obj.Snapshot._from_db_object(
            self.context, snapshot_obj.Snapshot(), fake_snapshot)
        snapshot.display_name = 'foobar'
        snapshot.metadata = {'key1': 'value1'}
        self.assertEqual({'display_name': 'foobar',
                          'metadata': {'key1': 'value1'}},
                         snapshot.obj_get_changes())
        snapshot.save(self.context)
        snapshot_update.assert_called_once_with(self.context, snapshot.id,
                                                {'display_name': 'foobar'})
        snapshot_metadata_update.assert_called_once_with(self.context, '1',
                                                         {'key1': 'value1'},
                                                         True)

    @mock.patch('cinder.db.snapshot_destroy')
    def test_destroy(self, snapshot_destroy):
        snapshot = snapshot_obj.Snapshot(context=self.context, id=1)
        snapshot.destroy()
        snapshot_destroy.assert_called_once_with(self.context, '1')

    @mock.patch('cinder.db.snapshot_metadata_delete')
    def test_delete_metadata_key(self, snapshot_metadata_delete):
        snapshot = snapshot_obj.Snapshot(self.context, id=1)
        snapshot.metadata = {'key1': 'value1', 'key2': 'value2'}
        self.assertEqual({}, snapshot._orig_metadata)
        snapshot.delete_metadata_key(self.context, 'key2')
        self.assertEqual({'key1': 'value1'}, snapshot.metadata)
        snapshot_metadata_delete.assert_called_once_with(self.context, '1',
                                                         'key2')

    def test_obj_fields(self):
        volume = volume_obj.Volume(context=self.context, id=2, _name_id=2)
        snapshot = snapshot_obj.Snapshot(context=self.context, id=1,
                                         volume=volume)
        self.assertEqual(['name', 'volume_name'], snapshot.obj_extra_fields)
        self.assertEqual('snapshot-1', snapshot.name)
        self.assertEqual('volume-2', snapshot.volume_name)

    @mock.patch('cinder.objects.volume.Volume.get_by_id')
    def test_obj_load_attr(self, volume_get_by_id):
        snapshot = snapshot_obj.Snapshot._from_db_object(
            self.context, snapshot_obj.Snapshot(), fake_snapshot)
        volume = volume_obj.Volume(context=self.context, id=2)
        volume_get_by_id.return_value = volume
        self.assertEqual(volume, snapshot.volume)
        volume_get_by_id.assert_called_once_with(self.context,
                                                 snapshot.volume_id)


class TestSnapshotList(test_objects._LocalTest):
    @mock.patch('cinder.db.snapshot_metadata_get', return_value={})
    @mock.patch('cinder.objects.Volume.get_by_id')
    @mock.patch('cinder.db.snapshot_get_all', return_value=[fake_snapshot])
    def test_get_all(self, snapshot_get_all, volume_get_by_id,
                     snapshot_metadata_get):
        fake_volume_obj = fake_volume.fake_volume_obj(self.context)
        volume_get_by_id.return_value = fake_volume_obj

        snapshots = snapshot_obj.SnapshotList.get_all(self.context)
        self.assertEqual(1, len(snapshots))
        TestSnapshot._compare(self, fake_snapshot, snapshots[0])

    @mock.patch('cinder.db.snapshot_metadata_get', return_value={})
    @mock.patch('cinder.objects.Volume.get_by_id')
    @mock.patch('cinder.db.snapshot_get_all_by_project',
                return_value=[fake_snapshot])
    def test_get_all_by_project(self, get_all_by_project, volume_get_by_id,
                                snapshot_metadata_get):
        fake_volume_obj = fake_volume.fake_volume_obj(self.context)
        volume_get_by_id.return_value = fake_volume_obj

        snapshots = snapshot_obj.SnapshotList.get_all_by_project(
            self.context, self.context.project_id)
        self.assertEqual(1, len(snapshots))
        TestSnapshot._compare(self, fake_snapshot, snapshots[0])

    @mock.patch('cinder.db.snapshot_metadata_get', return_value={})
    @mock.patch('cinder.objects.Volume.get_by_id')
    @mock.patch('cinder.db.snapshot_get_all_for_volume',
                return_value=[fake_snapshot])
    def test_get_all_for_volume(self, get_all_for_volume, volume_get_by_id,
                                snapshot_metadata_get):
        fake_volume_obj = fake_volume.fake_volume_obj(self.context)
        volume_get_by_id.return_value = fake_volume_obj

        snapshots = snapshot_obj.SnapshotList.get_all_for_volume(
            self.context, fake_volume_obj.id)
        self.assertEqual(1, len(snapshots))
        TestSnapshot._compare(self, fake_snapshot, snapshots[0])
