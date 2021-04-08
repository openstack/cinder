#    Copyright 2015 Red Hat, Inc.
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

import datetime
from unittest import mock
import uuid

import ddt
from iso8601 import iso8601
from oslo_versionedobjects import fields
from sqlalchemy import sql

from cinder import context
from cinder import db
from cinder.db.sqlalchemy import models
from cinder import exception
from cinder import objects
from cinder.objects import fields as c_fields
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_objects
from cinder.tests.unit import objects as test_objects
from cinder.tests.unit import test


class TestCinderObjectVersionHistory(test_objects.BaseObjectsTestCase):
    def test_add(self):
        history = test_objects.obj_base.CinderObjectVersionsHistory()
        first_version = history.versions[0]
        v10 = {'Backup': '2.0'}
        v11 = {'Backup': '2.1'}
        history.add('1.0', v10)
        history.add('1.1', v11)
        # We have 3 elements because we have the liberty version by default
        self.assertEqual(2 + 1, len(history))

        expected_v10 = history[first_version].copy()
        expected_v10.update(v10)
        expected_v11 = history[first_version].copy()
        expected_v11.update(v11)

        self.assertEqual('1.1', history.get_current())
        self.assertEqual(expected_v11, history.get_current_versions())
        self.assertEqual(expected_v10, history['1.0'])

    def test_add_existing(self):
        history = test_objects.obj_base.CinderObjectVersionsHistory()
        history.add('1.0', {'Backup': '1.0'})
        self.assertRaises(exception.ProgrammingError,
                          history.add, '1.0', {'Backup': '1.0'})


@ddt.ddt
class TestCinderObject(test_objects.BaseObjectsTestCase):
    """Tests methods from CinderObject."""

    def setUp(self):
        super(TestCinderObject, self).setUp()
        self.obj = fake_objects.ChildObject(
            scheduled_at=None,
            uuid=uuid.uuid4(),
            text='text')
        self.obj.obj_reset_changes()

    def test_cinder_obj_get_changes_no_changes(self):
        self.assertDictEqual({}, self.obj.cinder_obj_get_changes())

    def test_cinder_obj_get_changes_other_changes(self):
        self.obj.text = 'text2'
        self.assertDictEqual({'text': 'text2'},
                             self.obj.cinder_obj_get_changes())

    def test_cinder_obj_get_changes_datetime_no_tz(self):
        now = datetime.datetime.utcnow()
        self.obj.scheduled_at = now
        self.assertDictEqual({'scheduled_at': now},
                             self.obj.cinder_obj_get_changes())

    def test_cinder_obj_get_changes_datetime_tz_utc(self):
        now_tz = iso8601.parse_date('2015-06-26T22:00:01Z')
        now = now_tz.replace(tzinfo=None)
        self.obj.scheduled_at = now_tz
        self.assertDictEqual({'scheduled_at': now},
                             self.obj.cinder_obj_get_changes())

    def test_cinder_obj_get_changes_datetime_tz_non_utc_positive(self):
        now_tz = iso8601.parse_date('2015-06-26T22:00:01+01')
        now = now_tz.replace(tzinfo=None) - datetime.timedelta(hours=1)
        self.obj.scheduled_at = now_tz
        self.assertDictEqual({'scheduled_at': now},
                             self.obj.cinder_obj_get_changes())

    def test_cinder_obj_get_changes_datetime_tz_non_utc_negative(self):
        now_tz = iso8601.parse_date('2015-06-26T10:00:01-05')
        now = now_tz.replace(tzinfo=None) + datetime.timedelta(hours=5)
        self.obj.scheduled_at = now_tz
        self.assertDictEqual({'scheduled_at': now},
                             self.obj.cinder_obj_get_changes())

    @mock.patch('cinder.objects.base.CinderPersistentObject.get_by_id')
    def test_refresh(self, get_by_id):
        @objects.base.CinderObjectRegistry.register_if(False)
        class MyTestObject(objects.base.CinderObject,
                           objects.base.CinderObjectDictCompat,
                           objects.base.CinderComparableObject,
                           objects.base.CinderPersistentObject):
            fields = {'id': fields.UUIDField(),
                      'name': fields.StringField()}

        test_obj = MyTestObject(id=fake.OBJECT_ID, name='foo')
        refresh_obj = MyTestObject(id=fake.OBJECT_ID, name='bar')
        get_by_id.return_value = refresh_obj

        test_obj.refresh()
        self._compare(self, refresh_obj, test_obj)

    @mock.patch('cinder.objects.base.CinderPersistentObject.get_by_id')
    def test_refresh_readonly(self, get_by_id_mock):
        @objects.base.CinderObjectRegistry.register_if(False)
        class MyTestObject(objects.base.CinderObject,
                           objects.base.CinderObjectDictCompat,
                           objects.base.CinderComparableObject,
                           objects.base.CinderPersistentObject):
            fields = {'id': fields.UUIDField(),
                      'name': fields.StringField(read_only=True)}

        test_obj = MyTestObject(id=fake.OBJECT_ID, name='foo')
        refresh_obj = MyTestObject(id=fake.OBJECT_ID, name='bar')
        get_by_id_mock.return_value = refresh_obj

        test_obj.refresh()
        self._compare(self, refresh_obj, test_obj)

    def test_refresh_no_id_field(self):
        @objects.base.CinderObjectRegistry.register_if(False)
        class MyTestObjectNoId(objects.base.CinderObject,
                               objects.base.CinderObjectDictCompat,
                               objects.base.CinderComparableObject,
                               objects.base.CinderPersistentObject):
            fields = {'uuid': fields.UUIDField()}

        test_obj = MyTestObjectNoId(uuid=fake.OBJECT_ID, name='foo')
        self.assertRaises(NotImplementedError, test_obj.refresh)

    @mock.patch('cinder.objects.base.objects', mock.Mock())
    def test_cls_init(self):
        """Test that class init method gets called on registration."""
        @objects.base.CinderObjectRegistry.register
        class MyTestObject(objects.base.CinderObject,
                           objects.base.CinderPersistentObject):
            cinder_ovo_cls_init = mock.Mock()

        MyTestObject.cinder_ovo_cls_init.assert_called_once_with()

    def test_as_read_deleted_default(self):
        volume = objects.Volume(context=self.context)
        self.assertEqual('no', volume._context.read_deleted)
        with volume.as_read_deleted():
            self.assertEqual('yes', volume._context.read_deleted)
        self.assertEqual('no', volume._context.read_deleted)

    @ddt.data('yes', 'no', 'only')
    def test_as_read_deleted_modes(self, mode):
        volume = objects.Volume(context=self.context)
        self.assertEqual('no', volume._context.read_deleted)
        with volume.as_read_deleted(mode=mode):
            self.assertEqual(mode, volume._context.read_deleted)
        self.assertEqual('no', volume._context.read_deleted)


class TestCinderComparableObject(test_objects.BaseObjectsTestCase):
    def test_comparable_objects(self):
        @objects.base.CinderObjectRegistry.register
        class MyComparableObj(objects.base.CinderObject,
                              objects.base.CinderObjectDictCompat,
                              objects.base.CinderComparableObject):
            fields = {'foo': fields.Field(fields.Integer())}

        class NonVersionedObject(object):
            pass

        obj1 = MyComparableObj(foo=1)
        obj2 = MyComparableObj(foo=1)
        obj3 = MyComparableObj(foo=2)
        obj4 = NonVersionedObject()
        self.assertTrue(obj1 == obj2)
        self.assertFalse(obj1 == obj3)
        self.assertFalse(obj1 == obj4)
        self.assertIsNotNone(obj1)


@ddt.ddt
class TestCinderObjectConditionalUpdate(test.TestCase):

    def setUp(self):
        super(TestCinderObjectConditionalUpdate, self).setUp()
        self.context = context.get_admin_context()

    def _create_volume(self):
        vol = {
            'display_description': 'Test Desc',
            'size': 1,
            'status': 'available',
            'availability_zone': 'az',
            'host': 'dummy',
            'attach_status': c_fields.VolumeAttachStatus.DETACHED,
        }
        volume = objects.Volume(context=self.context, **vol)
        volume.create()
        return volume

    def _create_snapshot(self, volume):
        snapshot = objects.Snapshot(context=self.context, volume_id=volume.id)
        snapshot.create()
        return snapshot

    def _check_volume(self, volume, status, size, reload=False, dirty_keys=(),
                      **kwargs):
        if reload:
            volume = objects.Volume.get_by_id(self.context, volume.id)
        self.assertEqual(status, volume.status)
        self.assertEqual(size, volume.size)
        dirty = volume.cinder_obj_get_changes()
        self.assertEqual(list(dirty_keys), list(dirty.keys()))
        for key, value in kwargs.items():
            self.assertEqual(value, getattr(volume, key))

    def test_conditional_update_non_iterable_expected(self):
        volume = self._create_volume()
        # We also check that we can check for None values
        self.assertTrue(volume.conditional_update(
            {'status': 'deleting', 'size': 2},
            {'status': 'available', 'migration_status': None}))

        # Check that the object in memory has been updated
        self._check_volume(volume, 'deleting', 2)

        # Check that the volume in the DB also has been updated
        self._check_volume(volume, 'deleting', 2, True)

    def test_conditional_update_non_iterable_expected_model_field(self):
        volume = self._create_volume()
        # We also check that we can check for None values
        self.assertTrue(volume.conditional_update(
            {'status': 'deleting', 'size': 2,
             'previous_status': volume.model.status},
            {'status': 'available', 'migration_status': None}))

        # Check that the object in memory has been updated
        self._check_volume(volume, 'deleting', 2, previous_status='available')

        # Check that the volume in the DB also has been updated
        self._check_volume(volume, 'deleting', 2, True,
                           previous_status='available')

    def test_conditional_update_non_iterable_expected_save_all(self):
        volume = self._create_volume()
        volume.size += 1
        # We also check that we can check for not None values
        self.assertTrue(volume.conditional_update(
            {'status': 'deleting'},
            {'status': 'available', 'availability_zone': volume.Not(None)},
            save_all=True))

        # Check that the object in memory has been updated and that the size
        # is not a dirty key
        self._check_volume(volume, 'deleting', 2)

        # Check that the volume in the DB also has been updated
        self._check_volume(volume, 'deleting', 2, True)

    def test_conditional_update_non_iterable_expected_dont_save_all(self):
        volume = self._create_volume()
        volume.size += 1
        self.assertTrue(volume.conditional_update(
            {'status': 'deleting'},
            {'status': 'available'}, save_all=False))

        # Check that the object in memory has been updated with the new status
        # but that size has not been saved and is a dirty key
        self._check_volume(volume, 'deleting', 2, False, ['size'])

        # Check that the volume in the DB also has been updated but not the
        # size
        self._check_volume(volume, 'deleting', 1, True)

    def test_conditional_update_fail_non_iterable_expected_save_all(self):
        volume = self._create_volume()
        volume.size += 1
        self.assertFalse(volume.conditional_update(
            {'status': 'available'},
            {'status': 'deleting'}, save_all=True))

        # Check that the object in memory has not been updated and that the
        # size is still a dirty key
        self._check_volume(volume, 'available', 2, False, ['size'])

        # Check that the volume in the DB hasn't been updated
        self._check_volume(volume, 'available', 1, True)

    def test_default_conditional_update_non_iterable_expected(self):
        volume = self._create_volume()
        self.assertTrue(volume.conditional_update({'status': 'deleting'}))

        # Check that the object in memory has been updated
        self._check_volume(volume, 'deleting', 1)

        # Check that the volume in the DB also has been updated
        self._check_volume(volume, 'deleting', 1, True)

    def test_default_conditional_fail_update_non_iterable_expected(self):
        volume_in_db = self._create_volume()
        volume = objects.Volume.get_by_id(self.context, volume_in_db.id)
        volume_in_db.size += 1
        volume_in_db.save()
        # This will fail because size in DB is different
        self.assertFalse(volume.conditional_update({'status': 'deleting'}))

        # Check that the object in memory has not been updated
        self._check_volume(volume, 'available', 1)

        # Check that the volume in the DB hasn't changed the status but has
        # the size we changed before the conditional update
        self._check_volume(volume_in_db, 'available', 2, True)

    def test_default_conditional_update_non_iterable_expected_with_dirty(self):
        volume_in_db = self._create_volume()
        volume = objects.Volume.get_by_id(self.context, volume_in_db.id)
        volume_in_db.size += 1
        volume_in_db.save()
        volume.size = 33
        # This will fail because even though we have excluded the size from
        # the default condition when we dirtied it in the volume object, we
        # still have the last update timestamp that will be included in the
        # condition
        self.assertFalse(volume.conditional_update({'status': 'deleting'}))

        # Check that the object in memory has not been updated
        self._check_volume(volume, 'available', 33, False, ['size'])

        # Check that the volume in the DB hasn't changed the status but has
        # the size we changed before the conditional update
        self._check_volume(volume_in_db, 'available', 2, True)

    def test_conditional_update_negated_non_iterable_expected(self):
        volume = self._create_volume()
        self.assertTrue(volume.conditional_update(
            {'status': 'deleting', 'size': 2},
            {'status': db.Not('in-use'), 'size': db.Not(2)}))

        # Check that the object in memory has been updated
        self._check_volume(volume, 'deleting', 2)

        # Check that the volume in the DB also has been updated
        self._check_volume(volume, 'deleting', 2, True)

    def test_conditional_update_non_iterable_expected_filter(self):
        # Volume we want to change
        volume = self._create_volume()

        # Another volume that has no snapshots
        volume2 = self._create_volume()

        # A volume with snapshots
        volume3 = self._create_volume()
        self._create_snapshot(volume3)

        # Update only it it has no snapshot
        filters = (~sql.exists().where(
            models.Snapshot.volume_id == models.Volume.id),)

        self.assertTrue(volume.conditional_update(
            {'status': 'deleting', 'size': 2},
            {'status': 'available'},
            filters))

        # Check that the object in memory has been updated
        self._check_volume(volume, 'deleting', 2)

        # Check that the volume in the DB also has been updated
        self._check_volume(volume, 'deleting', 2, True)

        # Check that the other volumes in the DB haven't changed
        self._check_volume(volume2, 'available', 1, True)
        self._check_volume(volume3, 'available', 1, True)

    def test_conditional_update_iterable_expected(self):
        volume = self._create_volume()
        self.assertTrue(volume.conditional_update(
            {'status': 'deleting', 'size': 20},
            {'status': ('error', 'available'), 'size': range(10)}))

        # Check that the object in memory has been updated
        self._check_volume(volume, 'deleting', 20)

        # Check that the volume in the DB also has been updated
        self._check_volume(volume, 'deleting', 20, True)

    def test_conditional_update_negated_iterable_expected(self):
        volume = self._create_volume()
        self.assertTrue(volume.conditional_update(
            {'status': 'deleting', 'size': 20},
            {'status': db.Not(('creating', 'in-use')), 'size': range(10)}))

        # Check that the object in memory has been updated
        self._check_volume(volume, 'deleting', 20)

        # Check that the volume in the DB also has been updated
        self._check_volume(volume, 'deleting', 20, True)

    def test_conditional_update_fail_non_iterable_expected(self):
        volume = self._create_volume()
        self.assertFalse(volume.conditional_update(
            {'status': 'deleting'},
            {'status': 'available', 'size': 2}))

        # Check that the object in memory hasn't changed
        self._check_volume(volume, 'available', 1)

        # Check that the volume in the DB hasn't changed either
        self._check_volume(volume, 'available', 1, True)

    def test_conditional_update_fail_negated_non_iterable_expected(self):
        volume = self._create_volume()
        result = volume.conditional_update({'status': 'deleting'},
                                           {'status': db.Not('in-use'),
                                            'size': 2})
        self.assertFalse(result)

        # Check that the object in memory hasn't changed
        self._check_volume(volume, 'available', 1)

        # Check that the volume in the DB hasn't changed either
        self._check_volume(volume, 'available', 1, True)

    def test_conditional_update_fail_iterable_expected(self):
        volume = self._create_volume()
        self.assertFalse(volume.conditional_update(
            {'status': 'available'},
            {'status': ('error', 'creating'), 'size': range(2, 10)}))

        # Check that the object in memory hasn't changed
        self._check_volume(volume, 'available', 1)

        # Check that the volume in the DB hasn't changed either
        self._check_volume(volume, 'available', 1, True)

    def test_conditional_update_fail_negated_iterable_expected(self):
        volume = self._create_volume()
        self.assertFalse(volume.conditional_update(
            {'status': 'error'},
            {'status': db.Not(('available', 'in-use')), 'size': range(2, 10)}))

        # Check that the object in memory hasn't changed
        self._check_volume(volume, 'available', 1)

        # Check that the volume in the DB hasn't changed either
        self._check_volume(volume, 'available', 1, True)

    def test_conditional_update_fail_non_iterable_expected_filter(self):
        # Volume we want to change
        volume = self._create_volume()
        self._create_snapshot(volume)

        # A volume that has no snapshots
        volume2 = self._create_volume()

        # Another volume with snapshots
        volume3 = self._create_volume()
        self._create_snapshot(volume3)

        # Update only it it has no snapshot
        filters = (~sql.exists().where(
            models.Snapshot.volume_id == models.Volume.id),)

        self.assertFalse(volume.conditional_update(
            {'status': 'deleting', 'size': 2},
            {'status': 'available'},
            filters))

        # Check that the object in memory hasn't been updated
        self._check_volume(volume, 'available', 1)

        # Check that no volume in the DB also has been updated
        self._check_volume(volume, 'available', 1, True)
        self._check_volume(volume2, 'available', 1, True)
        self._check_volume(volume3, 'available', 1, True)

    def test_conditional_update_non_iterable_case_value(self):
        # Volume we want to change and has snapshots
        volume = self._create_volume()
        self._create_snapshot(volume)

        # Filter that checks if a volume has snapshots
        has_snapshot_filter = sql.exists().where(
            models.Snapshot.volume_id == models.Volume.id)

        # We want the updated value to depend on whether it has snapshots or
        # not
        case_values = volume.Case([(has_snapshot_filter, 'has-snapshot')],
                                  else_='no-snapshot')
        self.assertTrue(volume.conditional_update({'status': case_values},
                                                  {'status': 'available'}))

        # Check that the object in memory has been updated
        self._check_volume(volume, 'has-snapshot', 1)

        # Check that the volume in the DB also has been updated
        self._check_volume(volume, 'has-snapshot', 1, True)

    def test_conditional_update_non_iterable_case_value_else(self):
        # Volume we want to change
        volume = self._create_volume()

        # Filter that checks if a volume has snapshots
        has_snapshot_filter = sql.exists().where(
            models.Snapshot.volume_id == models.Volume.id)

        # We want the updated value to depend on whether it has snapshots or
        # not
        case_values = volume.Case([(has_snapshot_filter, 'has-snapshot')],
                                  else_='no-snapshot')
        self.assertTrue(volume.conditional_update({'status': case_values},
                                                  {'status': 'available'}))

        # Check that the object in memory has been updated
        self._check_volume(volume, 'no-snapshot', 1)

        # Check that the volume in the DB also has been updated
        self._check_volume(volume, 'no-snapshot', 1, True)

    def test_conditional_update_non_iterable_case_value_fail(self):
        # Volume we want to change doesn't have snapshots
        volume = self._create_volume()

        # Filter that checks if a volume has snapshots
        has_snapshot_filter = sql.exists().where(
            models.Snapshot.volume_id == models.Volume.id)

        # We want the updated value to depend on whether it has snapshots or
        # not
        case_values = volume.Case([(has_snapshot_filter, 'has-snapshot')],
                                  else_='no-snapshot')
        # We won't update because volume status is available
        self.assertFalse(volume.conditional_update({'status': case_values},
                                                   {'status': 'deleting'}))

        # Check that the object in memory has not been updated
        self._check_volume(volume, 'available', 1)

        # Check that the volume in the DB also hasn't been updated either
        self._check_volume(volume, 'available', 1, True)

    def test_conditional_update_iterable_with_none_expected(self):
        volume = self._create_volume()
        # We also check that we can check for None values in an iterable
        self.assertTrue(volume.conditional_update(
            {'status': 'deleting'},
            {'status': (None, 'available'),
             'migration_status': (None, 'finished')}))

        # Check that the object in memory has been updated
        self._check_volume(volume, 'deleting', 1)

        # Check that the volume in the DB also has been updated
        self._check_volume(volume, 'deleting', 1, True)

    def test_conditional_update_iterable_with_not_none_expected(self):
        volume = self._create_volume()
        # We also check that we can check for None values in a negated iterable
        self.assertTrue(volume.conditional_update(
            {'status': 'deleting'},
            {'status': volume.Not((None, 'in-use'))}))

        # Check that the object in memory has been updated
        self._check_volume(volume, 'deleting', 1)

        # Check that the volume in the DB also has been updated
        self._check_volume(volume, 'deleting', 1, True)

    def test_conditional_update_iterable_with_not_includes_null(self):
        volume = self._create_volume()
        # We also check that negation includes None values by default like we
        # do in Python and not like MySQL does
        self.assertTrue(volume.conditional_update(
            {'status': 'deleting'},
            {'status': 'available',
             'migration_status': volume.Not(('migrating', 'error'))}))

        # Check that the object in memory has been updated
        self._check_volume(volume, 'deleting', 1)

        # Check that the volume in the DB also has been updated
        self._check_volume(volume, 'deleting', 1, True)

    def test_conditional_update_iterable_with_not_includes_null_fails(self):
        volume = self._create_volume()
        # We also check that negation excludes None values if we ask it to
        self.assertFalse(volume.conditional_update(
            {'status': 'deleting'},
            {'status': 'available',
             'migration_status': volume.Not(('migrating', 'error'),
                                            auto_none=False)}))

        # Check that the object in memory has not been updated
        self._check_volume(volume, 'available', 1, False)

        # Check that the volume in the DB hasn't been updated
        self._check_volume(volume, 'available', 1, True)

    def test_conditional_update_use_operation_in_value(self):
        volume = self._create_volume()
        expected_size = volume.size + 1

        # We also check that using fields in requested changes will work as
        # expected
        self.assertTrue(volume.conditional_update(
            {'status': 'deleting',
             'size': volume.model.size + 1},
            {'status': 'available'}))

        # Check that the object in memory has been updated
        self._check_volume(volume, 'deleting', expected_size, False)

        # Check that the volume in the DB has also been updated
        self._check_volume(volume, 'deleting', expected_size, True)

    def test_conditional_update_auto_order(self):
        volume = self._create_volume()

        has_snapshot_filter = sql.exists().where(
            models.Snapshot.volume_id == models.Volume.id)

        case_values = volume.Case([(has_snapshot_filter, 'has-snapshot')],
                                  else_='no-snapshot')

        values = {'status': 'deleting',
                  'previous_status': volume.model.status,
                  'migration_status': case_values}

        with mock.patch('cinder.db.sqlalchemy.api.model_query') as model_query:
            update = model_query.return_value.filter.return_value.update
            update.return_value = 0
            self.assertFalse(volume.conditional_update(
                values, {'status': 'available'}))

        # We check that we are passing values to update to SQLAlchemy in the
        # right order
        self.assertEqual(1, update.call_count)
        self.assertListEqual(
            [('previous_status', volume.model.status),
             ('migration_status', mock.ANY),
             ('status', 'deleting')],
            list(update.call_args[0][0]))
        self.assertDictEqual(
            {'synchronize_session': False,
             'update_args': {'preserve_parameter_order': True}},
            update.call_args[1])

    def test_conditional_update_force_order(self):
        volume = self._create_volume()

        has_snapshot_filter = sql.exists().where(
            models.Snapshot.volume_id == models.Volume.id)

        case_values = volume.Case([(has_snapshot_filter, 'has-snapshot')],
                                  else_='no-snapshot')

        values = {'status': 'deleting',
                  'previous_status': volume.model.status,
                  'migration_status': case_values}

        order = ['status']

        with mock.patch('cinder.db.sqlalchemy.api.model_query') as model_query:
            update = model_query.return_value.filter.return_value.update
            update.return_value = 0
            self.assertFalse(volume.conditional_update(
                values, {'status': 'available'}, order=order))

        # We check that we are passing values to update to SQLAlchemy in the
        # right order
        self.assertEqual(1, update.call_count)
        self.assertListEqual(
            [('status', 'deleting'),
             ('previous_status', volume.model.status),
             ('migration_status', mock.ANY)],
            list(update.call_args[0][0]))
        self.assertDictEqual(
            {'synchronize_session': False,
             'update_args': {'preserve_parameter_order': True}},
            update.call_args[1])

    def test_conditional_update_no_order(self):
        volume = self._create_volume()

        values = {'status': 'deleting',
                  'previous_status': 'available',
                  'migration_status': None}

        with mock.patch('cinder.db.sqlalchemy.api.model_query') as model_query:
            update = model_query.return_value.filter.return_value.update
            update.return_value = 0
            self.assertFalse(volume.conditional_update(
                values, {'status': 'available'}))

        # Check that arguments passed to SQLAlchemy's update are correct (order
        # is not relevant).
        self.assertEqual(1, update.call_count)
        arg = update.call_args[0][0]
        self.assertIsInstance(arg, dict)
        self.assertEqual(set(values.keys()), set(arg.keys()))

    def test_conditional_update_multitable_fail(self):
        volume = self._create_volume()
        self.assertRaises(exception.ProgrammingError,
                          volume.conditional_update,
                          {'status': 'deleting',
                           objects.Snapshot.model.status: 'available'},
                          {'status': 'available'})

    def test_conditional_update_multitable_fail_fields_different_models(self):
        volume = self._create_volume()
        self.assertRaises(exception.ProgrammingError,
                          volume.conditional_update,
                          {objects.Backup.model.status: 'available',
                           objects.Snapshot.model.status: 'available'})

    @ddt.data(('available', 'error', None),
              ('error', 'rolling_back', [{'fake_filter': 'faked'}]))
    @ddt.unpack
    @mock.patch('cinder.objects.base.'
                'CinderPersistentObject.conditional_update')
    def test_update_status_where(self, value, expected, filters, mock_update):
        volume = self._create_volume()
        if filters:
            volume.update_single_status_where(value, expected, filters)
            mock_update.assert_called_with({'status': value},
                                           {'status': expected},
                                           filters)
        else:
            volume.update_single_status_where(value, expected)
            mock_update.assert_called_with({'status': value},
                                           {'status': expected},
                                           ())


class TestCinderDictObject(test_objects.BaseObjectsTestCase):
    @objects.base.CinderObjectRegistry.register_if(False)
    class TestDictObject(objects.base.CinderObjectDictCompat,
                         objects.base.CinderObject):
        obj_extra_fields = ['foo']

        fields = {
            'abc': fields.StringField(nullable=True),
            'def': fields.IntegerField(nullable=True),
        }

        @property
        def foo(self):
            return 42

    def test_dict_objects(self):
        obj = self.TestDictObject()
        self.assertNotIn('non_existing', obj)
        self.assertEqual('val', obj.get('abc', 'val'))
        self.assertNotIn('abc', obj)
        obj.abc = 'val2'
        self.assertEqual('val2', obj.get('abc', 'val'))
        self.assertEqual(42, obj.get('foo'))
        self.assertEqual(42, obj.get('foo', None))

        self.assertIn('foo', obj)
        self.assertIn('abc', obj)
        self.assertNotIn('def', obj)


@mock.patch('cinder.objects.base.OBJ_VERSIONS', fake_objects.MyHistory())
class TestCinderObjectSerializer(test_objects.BaseObjectsTestCase):
    BACKPORT_MSG = ('Backporting %(obj_name)s from version %(src_vers)s to '
                    'version %(dst_vers)s')

    def setUp(self):
        super(TestCinderObjectSerializer, self).setUp()
        self.obj = fake_objects.ChildObject(scheduled_at=None,
                                            uuid=uuid.uuid4(),
                                            text='text',
                                            integer=1)
        self.parent = fake_objects.ParentObject(uuid=uuid.uuid4(),
                                                child=self.obj,
                                                scheduled_at=None)
        self.parent_list = fake_objects.ParentObjectList(objects=[self.parent])

    def test_serialize_init_current_has_no_manifest(self):
        """Test that pinned to current version we have no manifest."""
        serializer = objects.base.CinderObjectSerializer('1.6')
        # Serializer should not have a manifest
        self.assertIsNone(serializer.manifest)

    def test_serialize_init_no_cap_has_no_manifest(self):
        """Test that without cap we have no manifest."""
        serializer = objects.base.CinderObjectSerializer()
        # Serializer should not have a manifest
        self.assertIsNone(serializer.manifest)

    def test_serialize_init_pinned_has_manifest(self):
        """Test that pinned to older version we have manifest."""
        objs_version = '1.5'
        serializer = objects.base.CinderObjectSerializer(objs_version)
        # Serializer should have the right manifest
        self.assertDictEqual(fake_objects.MyHistory()[objs_version],
                             serializer.manifest)

    def test_serialize_entity_unknown_version(self):
        """Test that bad cap version will prevent serializer creation."""
        self.assertRaises(exception.CappedVersionUnknown,
                          objects.base.CinderObjectSerializer, '0.9')

    @mock.patch('cinder.objects.base.LOG.debug')
    def test_serialize_entity_basic_no_backport(self, log_debug_mock):
        """Test single element serializer with no backport."""
        serializer = objects.base.CinderObjectSerializer('1.6')
        primitive = serializer.serialize_entity(self.context, self.obj)
        self.assertEqual('1.2', primitive['versioned_object.version'])
        data = primitive['versioned_object.data']
        self.assertEqual(1, data['integer'])
        self.assertEqual('text', data['text'])
        log_debug_mock.assert_not_called()

    @mock.patch('cinder.objects.base.LOG.debug')
    def test_serialize_entity_basic_backport(self, log_debug_mock):
        """Test single element serializer with backport."""
        serializer = objects.base.CinderObjectSerializer('1.5')
        primitive = serializer.serialize_entity(self.context, self.obj)
        self.assertEqual('1.1', primitive['versioned_object.version'])
        data = primitive['versioned_object.data']
        self.assertNotIn('integer', data)
        self.assertEqual('text', data['text'])
        log_debug_mock.assert_called_once_with(self.BACKPORT_MSG,
                                               {'obj_name': 'ChildObject',
                                                'src_vers': '1.2',
                                                'dst_vers': '1.1'})

    @mock.patch('cinder.objects.base.LOG.debug')
    def test_serialize_entity_full_no_backport(self, log_debug_mock):
        """Test related elements serialization with no backport."""
        serializer = objects.base.CinderObjectSerializer('1.6')
        primitive = serializer.serialize_entity(self.context, self.parent_list)
        self.assertEqual('1.1', primitive['versioned_object.version'])
        parent = primitive['versioned_object.data']['objects'][0]
        self.assertEqual('1.1', parent['versioned_object.version'])
        child = parent['versioned_object.data']['child']
        self.assertEqual('1.2', child['versioned_object.version'])
        log_debug_mock.assert_not_called()

    @mock.patch('cinder.objects.base.LOG.debug')
    def test_serialize_entity_full_backport_last_children(self,
                                                          log_debug_mock):
        """Test related elements serialization with backport of the last child.

        Test that using the manifest we properly backport a child object even
        when all its parents have not changed their version.
        """
        serializer = objects.base.CinderObjectSerializer('1.5')
        primitive = serializer.serialize_entity(self.context, self.parent_list)
        self.assertEqual('1.1', primitive['versioned_object.version'])
        parent = primitive['versioned_object.data']['objects'][0]
        self.assertEqual('1.1', parent['versioned_object.version'])
        # Only the child has been backported
        child = parent['versioned_object.data']['child']
        self.assertEqual('1.1', child['versioned_object.version'])
        # Check that the backport has been properly done
        data = child['versioned_object.data']
        self.assertNotIn('integer', data)
        self.assertEqual('text', data['text'])
        log_debug_mock.assert_called_once_with(self.BACKPORT_MSG,
                                               {'obj_name': 'ChildObject',
                                                'src_vers': '1.2',
                                                'dst_vers': '1.1'})

    @mock.patch('cinder.objects.base.LOG.debug')
    def test_serialize_entity_full_backport(self, log_debug_mock):
        """Test backport of the whole tree of related elements."""
        serializer = objects.base.CinderObjectSerializer('1.3')
        primitive = serializer.serialize_entity(self.context, self.parent_list)
        # List has been backported
        self.assertEqual('1.0', primitive['versioned_object.version'])
        parent = primitive['versioned_object.data']['objects'][0]
        # Parent has been backported as well
        self.assertEqual('1.0', parent['versioned_object.version'])
        # And the backport has been properly done
        data = parent['versioned_object.data']
        self.assertNotIn('scheduled_at', data)
        # And child as well
        child = parent['versioned_object.data']['child']
        self.assertEqual('1.1', child['versioned_object.version'])
        # Check that the backport has been properly done
        data = child['versioned_object.data']
        self.assertNotIn('integer', data)
        self.assertEqual('text', data['text'])
        log_debug_mock.assert_has_calls([
            mock.call(self.BACKPORT_MSG, {'obj_name': 'ParentObjectList',
                                          'src_vers': '1.1',
                                          'dst_vers': '1.0'}),
            mock.call(self.BACKPORT_MSG, {'obj_name': 'ParentObject',
                                          'src_vers': '1.1',
                                          'dst_vers': '1.0'}),
            mock.call(self.BACKPORT_MSG, {'obj_name': 'ChildObject',
                                          'src_vers': '1.2',
                                          'dst_vers': '1.1'})])
