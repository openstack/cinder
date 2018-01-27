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

import copy

import ddt
import mock
from oslo_utils import timeutils
import pytz
import six

from cinder.db.sqlalchemy import models
from cinder import exception
from cinder import objects
from cinder.objects import fields
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit import objects as test_objects


fake_db_snapshot = fake_snapshot.fake_db_snapshot(
    cgsnapshot_id=fake.CGSNAPSHOT_ID)
del fake_db_snapshot['metadata']
del fake_db_snapshot['volume']


# NOTE(andrey-mp): make Snapshot object here to check object algorithms
fake_snapshot_obj = {
    'id': fake.SNAPSHOT_ID,
    'volume_id': fake.VOLUME_ID,
    'status': fields.SnapshotStatus.CREATING,
    'progress': '0%',
    'volume_size': 1,
    'display_name': 'fake_name',
    'display_description': 'fake_description',
    'metadata': {},
}


@ddt.ddt
class TestSnapshot(test_objects.BaseObjectsTestCase):

    @mock.patch('cinder.db.get_by_id', return_value=fake_db_snapshot)
    def test_get_by_id(self, snapshot_get):
        snapshot = objects.Snapshot.get_by_id(self.context, 1)
        self._compare(self, fake_snapshot_obj, snapshot)
        snapshot_get.assert_called_once_with(self.context, models.Snapshot, 1)

    @mock.patch('cinder.db.sqlalchemy.api.model_query')
    def test_get_by_id_no_existing_id(self, model_query):
        query = model_query().options().options().filter_by().first
        query.return_value = None
        self.assertRaises(exception.SnapshotNotFound,
                          objects.Snapshot.get_by_id, self.context, 123)

    def test_reset_changes(self):
        snapshot = objects.Snapshot()
        snapshot.metadata = {'key1': 'value1'}
        self.assertEqual({}, snapshot._orig_metadata)
        snapshot.obj_reset_changes(['metadata'])
        self.assertEqual({'key1': 'value1'}, snapshot._orig_metadata)

    @mock.patch('cinder.db.snapshot_create', return_value=fake_db_snapshot)
    def test_create(self, snapshot_create):
        snapshot = objects.Snapshot(context=self.context)
        snapshot.create()
        self.assertEqual(fake_snapshot_obj['id'], snapshot.id)
        self.assertEqual(fake_snapshot_obj['volume_id'], snapshot.volume_id)

    @mock.patch('cinder.db.snapshot_create')
    def test_create_with_provider_id(self, snapshot_create):
        snapshot_create.return_value = copy.deepcopy(fake_db_snapshot)
        snapshot_create.return_value['provider_id'] = fake.PROVIDER_ID

        snapshot = objects.Snapshot(context=self.context)
        snapshot.create()
        self.assertEqual(fake.PROVIDER_ID, snapshot.provider_id)

    @mock.patch('cinder.db.snapshot_update')
    def test_save(self, snapshot_update):
        snapshot = objects.Snapshot._from_db_object(
            self.context, objects.Snapshot(), fake_db_snapshot)
        snapshot.display_name = 'foobar'
        snapshot.save()
        snapshot_update.assert_called_once_with(self.context, snapshot.id,
                                                {'display_name': 'foobar'})

    @mock.patch('cinder.db.snapshot_metadata_update',
                return_value={'key1': 'value1'})
    @mock.patch('cinder.db.snapshot_update')
    def test_save_with_metadata(self, snapshot_update,
                                snapshot_metadata_update):
        snapshot = objects.Snapshot._from_db_object(
            self.context, objects.Snapshot(), fake_db_snapshot)
        snapshot.display_name = 'foobar'
        snapshot.metadata = {'key1': 'value1'}
        self.assertEqual({'display_name': 'foobar',
                          'metadata': {'key1': 'value1'}},
                         snapshot.obj_get_changes())
        snapshot.save()
        snapshot_update.assert_called_once_with(self.context, snapshot.id,
                                                {'display_name': 'foobar'})
        snapshot_metadata_update.assert_called_once_with(self.context,
                                                         fake.SNAPSHOT_ID,
                                                         {'key1': 'value1'},
                                                         True)

    @mock.patch('oslo_utils.timeutils.utcnow', return_value=timeutils.utcnow())
    @mock.patch('cinder.db.sqlalchemy.api.snapshot_destroy')
    def test_destroy(self, snapshot_destroy, utcnow_mock):
        snapshot_destroy.return_value = {
            'status': 'deleted',
            'deleted': True,
            'deleted_at': utcnow_mock.return_value}
        snapshot = objects.Snapshot(context=self.context,
                                    id=fake.SNAPSHOT_ID)
        snapshot.destroy()
        self.assertTrue(snapshot_destroy.called)
        admin_context = snapshot_destroy.call_args[0][0]
        self.assertTrue(admin_context.is_admin)
        self.assertTrue(snapshot.deleted)
        self.assertEqual(fields.SnapshotStatus.DELETED, snapshot.status)
        self.assertEqual(utcnow_mock.return_value.replace(tzinfo=pytz.UTC),
                         snapshot.deleted_at)

    @mock.patch('cinder.db.snapshot_metadata_delete')
    def test_delete_metadata_key(self, snapshot_metadata_delete):
        snapshot = objects.Snapshot(self.context, id=fake.SNAPSHOT_ID)
        snapshot.metadata = {'key1': 'value1', 'key2': 'value2'}
        self.assertEqual({}, snapshot._orig_metadata)
        snapshot.delete_metadata_key(self.context, 'key2')
        self.assertEqual({'key1': 'value1'}, snapshot.metadata)
        snapshot_metadata_delete.assert_called_once_with(self.context,
                                                         fake.SNAPSHOT_ID,
                                                         'key2')

    def test_obj_fields(self):
        volume = objects.Volume(context=self.context, id=fake.VOLUME_ID,
                                _name_id=fake.VOLUME_NAME_ID)
        snapshot = objects.Snapshot(context=self.context, id=fake.VOLUME_ID,
                                    volume=volume)
        self.assertEqual(['name', 'volume_name'], snapshot.obj_extra_fields)
        self.assertEqual('snapshot-%s' % fake.VOLUME_ID, snapshot.name)
        self.assertEqual('volume-%s' % fake.VOLUME_NAME_ID,
                         snapshot.volume_name)

    @mock.patch('cinder.objects.volume.Volume.get_by_id')
    @mock.patch('cinder.objects.cgsnapshot.CGSnapshot.get_by_id')
    def test_obj_load_attr(self, cgsnapshot_get_by_id, volume_get_by_id):
        snapshot = objects.Snapshot._from_db_object(
            self.context, objects.Snapshot(), fake_db_snapshot)
        # Test volume lazy-loaded field
        volume = objects.Volume(context=self.context, id=fake.VOLUME_ID)
        volume_get_by_id.return_value = volume
        self.assertEqual(volume, snapshot.volume)
        volume_get_by_id.assert_called_once_with(self.context,
                                                 snapshot.volume_id)
        # Test cgsnapshot lazy-loaded field
        cgsnapshot = objects.CGSnapshot(context=self.context,
                                        id=fake.CGSNAPSHOT_ID)
        cgsnapshot_get_by_id.return_value = cgsnapshot
        self.assertEqual(cgsnapshot, snapshot.cgsnapshot)
        cgsnapshot_get_by_id.assert_called_once_with(self.context,
                                                     snapshot.cgsnapshot_id)

    @mock.patch('cinder.objects.cgsnapshot.CGSnapshot.get_by_id')
    def test_obj_load_attr_cgroup_not_exist(self, cgsnapshot_get_by_id):
        fake_non_cg_db_snapshot = fake_snapshot.fake_db_snapshot(
            cgsnapshot_id=None)
        snapshot = objects.Snapshot._from_db_object(
            self.context, objects.Snapshot(), fake_non_cg_db_snapshot)
        self.assertIsNone(snapshot.cgsnapshot)
        cgsnapshot_get_by_id.assert_not_called()

    @mock.patch('cinder.objects.group_snapshot.GroupSnapshot.get_by_id')
    def test_obj_load_attr_group_not_exist(self, group_snapshot_get_by_id):
        fake_non_cg_db_snapshot = fake_snapshot.fake_db_snapshot(
            group_snapshot_id=None)
        snapshot = objects.Snapshot._from_db_object(
            self.context, objects.Snapshot(), fake_non_cg_db_snapshot)
        self.assertIsNone(snapshot.group_snapshot)
        group_snapshot_get_by_id.assert_not_called()

    @mock.patch('cinder.db.snapshot_data_get_for_project')
    def test_snapshot_data_get_for_project(self, snapshot_data_get):
        snapshot = objects.Snapshot._from_db_object(
            self.context, objects.Snapshot(), fake_db_snapshot)
        volume_type_id = mock.sentinel.volume_type_id
        snapshot.snapshot_data_get_for_project(self.context,
                                               self.project_id,
                                               volume_type_id)
        snapshot_data_get.assert_called_once_with(self.context,
                                                  self.project_id,
                                                  volume_type_id)

    @mock.patch('cinder.db.sqlalchemy.api.snapshot_get')
    def test_refresh(self, snapshot_get):
        db_snapshot1 = fake_snapshot.fake_db_snapshot()
        db_snapshot2 = db_snapshot1.copy()
        db_snapshot2['display_name'] = 'foobar'

        # On the second snapshot_get, return the snapshot with an updated
        # display_name
        snapshot_get.side_effect = [db_snapshot1, db_snapshot2]
        snapshot = objects.Snapshot.get_by_id(self.context, fake.SNAPSHOT_ID)
        self._compare(self, db_snapshot1, snapshot)

        # display_name was updated, so a snapshot refresh should have a new
        # value for that field
        snapshot.refresh()
        self._compare(self, db_snapshot2, snapshot)
        if six.PY3:
            call_bool = mock.call.__bool__()
        else:
            call_bool = mock.call.__nonzero__()
        snapshot_get.assert_has_calls([
            mock.call(self.context,
                      fake.SNAPSHOT_ID),
            call_bool,
            mock.call(self.context,
                      fake.SNAPSHOT_ID)])

    @ddt.data('1.1', '1.3')
    def test_obj_make_compatible_1_3(self, version):
        snapshot = objects.Snapshot(context=self.context)
        snapshot.status = fields.SnapshotStatus.UNMANAGING
        primitive = snapshot.obj_to_primitive(version)
        snapshot = objects.Snapshot.obj_from_primitive(primitive)
        if version == '1.3':
            status = fields.SnapshotStatus.UNMANAGING
        else:
            status = fields.SnapshotStatus.DELETING
        self.assertEqual(status, snapshot.status)

    @ddt.data('1.3', '1.4')
    def test_obj_make_compatible_1_4(self, version):
        snapshot = objects.Snapshot(context=self.context)
        snapshot.status = fields.SnapshotStatus.BACKING_UP
        primitive = snapshot.obj_to_primitive(version)
        snapshot = objects.Snapshot.obj_from_primitive(primitive)
        if version == '1.4':
            status = fields.SnapshotStatus.BACKING_UP
        else:
            status = fields.SnapshotStatus.AVAILABLE
        self.assertEqual(status, snapshot.status)


class TestSnapshotList(test_objects.BaseObjectsTestCase):
    @mock.patch('cinder.objects.volume.Volume.get_by_id')
    @mock.patch('cinder.db.snapshot_get_all', return_value=[fake_db_snapshot])
    def test_get_all(self, snapshot_get_all, volume_get_by_id):
        fake_volume_obj = fake_volume.fake_volume_obj(self.context)
        volume_get_by_id.return_value = fake_volume_obj

        search_opts = mock.sentinel.search_opts
        snapshots = objects.SnapshotList.get_all(
            self.context, search_opts)
        self.assertEqual(1, len(snapshots))
        TestSnapshot._compare(self, fake_snapshot_obj, snapshots[0])
        snapshot_get_all.assert_called_once_with(self.context, search_opts,
                                                 None, None, None, None, None)

    @mock.patch('cinder.objects.Volume.get_by_id')
    @mock.patch('cinder.db.snapshot_get_all_by_host',
                return_value=[fake_db_snapshot])
    def test_get_by_host(self, get_by_host, volume_get_by_id):
        fake_volume_obj = fake_volume.fake_volume_obj(self.context)
        volume_get_by_id.return_value = fake_volume_obj

        snapshots = objects.SnapshotList.get_by_host(
            self.context, 'fake-host')
        self.assertEqual(1, len(snapshots))
        TestSnapshot._compare(self, fake_snapshot_obj, snapshots[0])

    @mock.patch('cinder.objects.volume.Volume.get_by_id')
    @mock.patch('cinder.db.snapshot_get_all_by_project',
                return_value=[fake_db_snapshot])
    def test_get_all_by_project(self, get_all_by_project, volume_get_by_id):
        fake_volume_obj = fake_volume.fake_volume_obj(self.context)
        volume_get_by_id.return_value = fake_volume_obj

        search_opts = mock.sentinel.search_opts
        snapshots = objects.SnapshotList.get_all_by_project(
            self.context, self.project_id, search_opts)
        self.assertEqual(1, len(snapshots))
        TestSnapshot._compare(self, fake_snapshot_obj, snapshots[0])
        get_all_by_project.assert_called_once_with(self.context,
                                                   self.project_id,
                                                   search_opts, None, None,
                                                   None, None, None)

    @mock.patch('cinder.objects.volume.Volume.get_by_id')
    @mock.patch('cinder.db.snapshot_get_all_for_volume',
                return_value=[fake_db_snapshot])
    def test_get_all_for_volume(self, get_all_for_volume, volume_get_by_id):
        fake_volume_obj = fake_volume.fake_volume_obj(self.context)
        volume_get_by_id.return_value = fake_volume_obj

        snapshots = objects.SnapshotList.get_all_for_volume(
            self.context, fake_volume_obj.id)
        self.assertEqual(1, len(snapshots))
        TestSnapshot._compare(self, fake_snapshot_obj, snapshots[0])

    @mock.patch('cinder.objects.volume.Volume.get_by_id')
    @mock.patch('cinder.db.snapshot_get_all_active_by_window',
                return_value=[fake_db_snapshot])
    def test_get_all_active_by_window(self, get_all_active_by_window,
                                      volume_get_by_id):
        fake_volume_obj = fake_volume.fake_volume_obj(self.context)
        volume_get_by_id.return_value = fake_volume_obj

        snapshots = objects.SnapshotList.get_all_active_by_window(
            self.context, mock.sentinel.begin, mock.sentinel.end)
        self.assertEqual(1, len(snapshots))
        TestSnapshot._compare(self, fake_snapshot_obj, snapshots[0])

    @mock.patch('cinder.objects.volume.Volume.get_by_id')
    @mock.patch('cinder.db.snapshot_get_all_for_cgsnapshot',
                return_value=[fake_db_snapshot])
    def test_get_all_for_cgsnapshot(self, get_all_for_cgsnapshot,
                                    volume_get_by_id):
        fake_volume_obj = fake_volume.fake_volume_obj(self.context)
        volume_get_by_id.return_value = fake_volume_obj

        snapshots = objects.SnapshotList.get_all_for_cgsnapshot(
            self.context, mock.sentinel.cgsnapshot_id)
        self.assertEqual(1, len(snapshots))
        TestSnapshot._compare(self, fake_snapshot_obj, snapshots[0])

    @mock.patch('cinder.objects.volume.Volume.get_by_id')
    @mock.patch('cinder.db.snapshot_get_all')
    def test_get_all_without_metadata(self, snapshot_get_all,
                                      volume_get_by_id):
        fake_volume_obj = fake_volume.fake_volume_obj(self.context)
        volume_get_by_id.return_value = fake_volume_obj

        snapshot = copy.deepcopy(fake_db_snapshot)
        del snapshot['snapshot_metadata']
        snapshot_get_all.return_value = [snapshot]

        search_opts = mock.sentinel.search_opts
        self.assertRaises(exception.MetadataAbsent,
                          objects.SnapshotList.get_all,
                          self.context, search_opts)

    @mock.patch('cinder.objects.volume.Volume.get_by_id')
    @mock.patch('cinder.db.snapshot_get_all')
    def test_get_all_with_metadata(self, snapshot_get_all, volume_get_by_id):
        fake_volume_obj = fake_volume.fake_volume_obj(self.context)
        volume_get_by_id.return_value = fake_volume_obj

        db_snapshot = copy.deepcopy(fake_db_snapshot)
        db_snapshot['snapshot_metadata'] = [{'key': 'fake_key',
                                             'value': 'fake_value'}]
        snapshot_get_all.return_value = [db_snapshot]

        search_opts = mock.sentinel.search_opts
        snapshots = objects.SnapshotList.get_all(
            self.context, search_opts)
        self.assertEqual(1, len(snapshots))

        snapshot_obj = copy.deepcopy(fake_snapshot_obj)
        snapshot_obj['metadata'] = {'fake_key': 'fake_value'}
        TestSnapshot._compare(self, snapshot_obj, snapshots[0])
        snapshot_get_all.assert_called_once_with(self.context, search_opts,
                                                 None, None, None, None, None)
