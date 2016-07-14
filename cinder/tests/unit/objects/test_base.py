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
import uuid

from iso8601 import iso8601
import mock
from oslo_versionedobjects import fields
from sqlalchemy import sql

from cinder import context
from cinder import db
from cinder.db.sqlalchemy import models
from cinder import exception
from cinder import objects
from cinder import test
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_objects
from cinder.tests.unit import objects as test_objects


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

    def test_refresh(self):
        @objects.base.CinderObjectRegistry.register_if(False)
        class MyTestObject(objects.base.CinderObject,
                           objects.base.CinderObjectDictCompat,
                           objects.base.CinderComparableObject):
            fields = {'id': fields.UUIDField(),
                      'name': fields.StringField()}

        test_obj = MyTestObject(id=fake.object_id, name='foo')
        refresh_obj = MyTestObject(id=fake.object_id, name='bar')
        with mock.patch(
                'cinder.objects.base.CinderObject.get_by_id') as get_by_id:
            get_by_id.return_value = refresh_obj

            test_obj.refresh()
            self._compare(self, refresh_obj, test_obj)

    def test_refresh_no_id_field(self):
        @objects.base.CinderObjectRegistry.register_if(False)
        class MyTestObjectNoId(objects.base.CinderObject,
                               objects.base.CinderObjectDictCompat,
                               objects.base.CinderComparableObject):
            fields = {'uuid': fields.UUIDField()}

        test_obj = MyTestObjectNoId(uuid=fake.object_id, name='foo')
        self.assertRaises(NotImplementedError, test_obj.refresh)


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
        self.assertNotEqual(obj1, None)


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
            'attach_status': 'no',
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
        self.assertIsNone(obj.get('non_existing'))
        self.assertEqual('val', obj.get('abc', 'val'))
        self.assertIsNone(obj.get('abc'))
        obj.abc = 'val2'
        self.assertEqual('val2', obj.get('abc', 'val'))
        self.assertEqual(42, obj.get('foo'))
        self.assertEqual(42, obj.get('foo', None))

        self.assertTrue('foo' in obj)
        self.assertTrue('abc' in obj)
        self.assertFalse('def' in obj)


@mock.patch('cinder.objects.base.OBJ_VERSIONS', fake_objects.MyHistory())
class TestCinderObjectSerializer(test_objects.BaseObjectsTestCase):
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

    def test_serialize_entity_basic_no_backport(self):
        """Test single element serializer with no backport."""
        serializer = objects.base.CinderObjectSerializer('1.6')
        primitive = serializer.serialize_entity(self.context, self.obj)
        self.assertEqual('1.2', primitive['versioned_object.version'])
        data = primitive['versioned_object.data']
        self.assertEqual(1, data['integer'])
        self.assertEqual('text', data['text'])

    def test_serialize_entity_basic_backport(self):
        """Test single element serializer with backport."""
        serializer = objects.base.CinderObjectSerializer('1.5')
        primitive = serializer.serialize_entity(self.context, self.obj)
        self.assertEqual('1.1', primitive['versioned_object.version'])
        data = primitive['versioned_object.data']
        self.assertNotIn('integer', data)
        self.assertEqual('text', data['text'])

    def test_serialize_entity_full_no_backport(self):
        """Test related elements serialization with no backport."""
        serializer = objects.base.CinderObjectSerializer('1.6')
        primitive = serializer.serialize_entity(self.context, self.parent_list)
        self.assertEqual('1.1', primitive['versioned_object.version'])
        parent = primitive['versioned_object.data']['objects'][0]
        self.assertEqual('1.1', parent['versioned_object.version'])
        child = parent['versioned_object.data']['child']
        self.assertEqual('1.2', child['versioned_object.version'])

    def test_serialize_entity_full_backport_last_children(self):
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

    def test_serialize_entity_full_backport(self):
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
