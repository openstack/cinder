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

import ddt
import mock
from oslo_utils import timeutils
import pytz
import six

from cinder import context
from cinder import exception
from cinder import objects
from cinder.objects import base as ovo_base
from cinder.objects import fields
from cinder.tests.unit.consistencygroup import fake_consistencygroup
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit import objects as test_objects


@ddt.ddt
class TestVolume(test_objects.BaseObjectsTestCase):
    @staticmethod
    def _compare(test, db, obj):
        db = {k: v for k, v in db.items()
              if not k.endswith('metadata') or k.startswith('volume')}
        test_objects.BaseObjectsTestCase._compare(test, db, obj)

    @mock.patch('cinder.db.sqlalchemy.api.volume_get')
    def test_get_by_id(self, volume_get):
        db_volume = fake_volume.fake_db_volume()
        volume_get.return_value = db_volume
        volume = objects.Volume.get_by_id(self.context, fake.VOLUME_ID)
        volume_get.assert_called_once_with(self.context, fake.VOLUME_ID)
        self._compare(self, db_volume, volume)

    @mock.patch('cinder.db.sqlalchemy.api.model_query')
    def test_get_by_id_no_existing_id(self, model_query):
        pf = (model_query().options().options().options().options().options().
              options())
        pf.filter_by().first.return_value = None
        self.assertRaises(exception.VolumeNotFound,
                          objects.Volume.get_by_id, self.context, 123)

    @mock.patch('cinder.db.volume_create')
    def test_create(self, volume_create):
        db_volume = fake_volume.fake_db_volume()
        volume_create.return_value = db_volume
        volume = objects.Volume(context=self.context)
        volume.create()
        self.assertEqual(db_volume['id'], volume.id)

    @mock.patch('cinder.db.volume_update')
    @ddt.data(False, True)
    def test_save(self, test_cg, volume_update):
        db_volume = fake_volume.fake_db_volume()
        volume = objects.Volume._from_db_object(self.context,
                                                objects.Volume(), db_volume)
        volume.display_name = 'foobar'
        if test_cg:
            volume.consistencygroup = None
        volume.save()
        volume_update.assert_called_once_with(self.context, volume.id,
                                              {'display_name': 'foobar'})

    def test_save_error(self):
        db_volume = fake_volume.fake_db_volume()
        volume = objects.Volume._from_db_object(self.context,
                                                objects.Volume(), db_volume)
        volume.display_name = 'foobar'
        volume.consistencygroup = (
            fake_consistencygroup.fake_consistencyobject_obj(self.context))
        self.assertRaises(exception.ObjectActionError,
                          volume.save)

    @mock.patch('cinder.db.volume_metadata_update',
                return_value={'key1': 'value1'})
    @mock.patch('cinder.db.volume_update')
    def test_save_with_metadata(self, volume_update, metadata_update):
        db_volume = fake_volume.fake_db_volume()
        volume = objects.Volume._from_db_object(self.context,
                                                objects.Volume(), db_volume)
        volume.display_name = 'foobar'
        volume.metadata = {'key1': 'value1'}
        self.assertEqual({'display_name': 'foobar',
                          'metadata': {'key1': 'value1'}},
                         volume.obj_get_changes())
        volume.save()
        volume_update.assert_called_once_with(self.context, volume.id,
                                              {'display_name': 'foobar'})
        metadata_update.assert_called_once_with(self.context, volume.id,
                                                {'key1': 'value1'}, True)

    @mock.patch('cinder.db.volume_admin_metadata_update',
                return_value={'key1': 'value1'})
    @mock.patch('cinder.db.volume_update')
    def test_save_with_admin_metadata(self, volume_update,
                                      admin_metadata_update):
        # Test with no admin context
        db_volume = fake_volume.fake_db_volume()
        volume = objects.Volume._from_db_object(self.context,
                                                objects.Volume(), db_volume)
        volume.admin_metadata = {'key1': 'value1'}
        volume.save()
        self.assertFalse(admin_metadata_update.called)

        # Test with admin context
        admin_context = context.RequestContext(self.user_id, self.project_id,
                                               is_admin=True)
        volume = objects.Volume._from_db_object(admin_context,
                                                objects.Volume(), db_volume)
        volume.admin_metadata = {'key1': 'value1'}
        volume.save()
        admin_metadata_update.assert_called_once_with(
            admin_context, volume.id, {'key1': 'value1'}, True)

    def test_save_with_glance_metadata(self):
        db_volume = fake_volume.fake_db_volume()
        volume = objects.Volume._from_db_object(self.context,
                                                objects.Volume(), db_volume)
        volume.display_name = 'foobar'
        volume.glance_metadata = {'key1': 'value1'}
        self.assertRaises(exception.ObjectActionError, volume.save)

    def test_save_with_consistencygroup(self):
        db_volume = fake_volume.fake_db_volume()
        volume = objects.Volume._from_db_object(self.context,
                                                objects.Volume(), db_volume)
        volume.display_name = 'foobar'
        volume.consistencygroup = objects.ConsistencyGroup()
        self.assertRaises(exception.ObjectActionError, volume.save)

    def test_save_with_snapshots(self):
        db_volume = fake_volume.fake_db_volume()
        volume = objects.Volume._from_db_object(self.context,
                                                objects.Volume(), db_volume)
        volume.display_name = 'foobar'
        volume.snapshots = objects.SnapshotList()
        self.assertRaises(exception.ObjectActionError, volume.save)

    @mock.patch('oslo_utils.timeutils.utcnow', return_value=timeutils.utcnow())
    @mock.patch('cinder.db.sqlalchemy.api.volume_destroy')
    def test_destroy(self, volume_destroy, utcnow_mock):
        volume_destroy.return_value = {
            'status': 'deleted',
            'deleted': True,
            'deleted_at': utcnow_mock.return_value}
        db_volume = fake_volume.fake_db_volume()
        volume = objects.Volume._from_db_object(self.context,
                                                objects.Volume(), db_volume)
        volume.destroy()
        self.assertTrue(volume_destroy.called)
        admin_context = volume_destroy.call_args[0][0]
        self.assertTrue(admin_context.is_admin)
        self.assertTrue(volume.deleted)
        self.assertEqual('deleted', volume.status)
        self.assertEqual(utcnow_mock.return_value.replace(tzinfo=pytz.UTC),
                         volume.deleted_at)
        self.assertIsNone(volume.migration_status)

    def test_obj_fields(self):
        volume = objects.Volume(context=self.context, id=fake.VOLUME_ID,
                                name_id=fake.VOLUME_NAME_ID)
        self.assertEqual(['name', 'name_id', 'volume_metadata',
                          'volume_admin_metadata', 'volume_glance_metadata'],
                         volume.obj_extra_fields)
        self.assertEqual('volume-%s' % fake.VOLUME_NAME_ID, volume.name)
        self.assertEqual(fake.VOLUME_NAME_ID, volume.name_id)

    def test_obj_field_previous_status(self):
        volume = objects.Volume(context=self.context,
                                previous_status='backing-up')
        self.assertEqual('backing-up', volume.previous_status)

    @mock.patch('cinder.db.volume_metadata_delete')
    def test_delete_metadata_key(self, metadata_delete):
        volume = objects.Volume(self.context, id=fake.VOLUME_ID)
        volume.metadata = {'key1': 'value1', 'key2': 'value2'}
        self.assertEqual({}, volume._orig_metadata)
        volume.delete_metadata_key('key2')
        self.assertEqual({'key1': 'value1'}, volume.metadata)
        metadata_delete.assert_called_once_with(self.context, fake.VOLUME_ID,
                                                'key2')

    @mock.patch('cinder.db.volume_metadata_get')
    @mock.patch('cinder.db.volume_glance_metadata_get')
    @mock.patch('cinder.db.volume_admin_metadata_get')
    @mock.patch('cinder.objects.volume_type.VolumeType.get_by_id')
    @mock.patch('cinder.objects.volume_attachment.VolumeAttachmentList.'
                'get_all_by_volume_id')
    @mock.patch('cinder.objects.consistencygroup.ConsistencyGroup.get_by_id')
    @mock.patch('cinder.objects.snapshot.SnapshotList.get_all_for_volume')
    def test_obj_load_attr(self, mock_sl_get_all_for_volume, mock_cg_get_by_id,
                           mock_va_get_all_by_vol, mock_vt_get_by_id,
                           mock_admin_metadata_get, mock_glance_metadata_get,
                           mock_metadata_get):
        fake_db_volume = fake_volume.fake_db_volume(
            consistencygroup_id=fake.CONSISTENCY_GROUP_ID)
        volume = objects.Volume._from_db_object(
            self.context, objects.Volume(), fake_db_volume)

        # Test metadata lazy-loaded field
        metadata = {'foo': 'bar'}
        mock_metadata_get.return_value = metadata
        self.assertEqual(metadata, volume.metadata)
        mock_metadata_get.assert_called_once_with(self.context, volume.id)

        # Test glance_metadata lazy-loaded field
        glance_metadata = [{'key': 'foo', 'value': 'bar'}]
        mock_glance_metadata_get.return_value = glance_metadata
        self.assertEqual({'foo': 'bar'}, volume.glance_metadata)
        mock_glance_metadata_get.assert_called_once_with(
            self.context, volume.id)

        # Test volume_type lazy-loaded field
        # Case1. volume.volume_type_id = None
        self.assertIsNone(volume.volume_type)

        # Case2. volume2.volume_type_id = 1
        fake2 = fake_volume.fake_db_volume()
        fake2.update({'volume_type_id': fake.VOLUME_ID})
        volume2 = objects.Volume._from_db_object(
            self.context, objects.Volume(), fake2)
        volume_type = objects.VolumeType(context=self.context,
                                         id=fake.VOLUME_TYPE_ID)
        mock_vt_get_by_id.return_value = volume_type
        self.assertEqual(volume_type, volume2.volume_type)
        mock_vt_get_by_id.assert_called_once_with(self.context,
                                                  volume2.volume_type_id)

        # Test consistencygroup lazy-loaded field
        consistencygroup = objects.ConsistencyGroup(
            context=self.context, id=fake.CONSISTENCY_GROUP_ID)
        mock_cg_get_by_id.return_value = consistencygroup
        self.assertEqual(consistencygroup, volume.consistencygroup)
        mock_cg_get_by_id.assert_called_once_with(self.context,
                                                  volume.consistencygroup_id)

        # Test snapshots lazy-loaded field
        snapshots = objects.SnapshotList(context=self.context,
                                         id=fake.SNAPSHOT_ID)
        mock_sl_get_all_for_volume.return_value = snapshots
        self.assertEqual(snapshots, volume.snapshots)
        mock_sl_get_all_for_volume.assert_called_once_with(self.context,
                                                           volume.id)

        # Test volume_attachment lazy-loaded field
        va_objs = [objects.VolumeAttachment(context=self.context, id=i)
                   for i in [fake.OBJECT_ID, fake.OBJECT2_ID, fake.OBJECT3_ID]]
        va_list = objects.VolumeAttachmentList(context=self.context,
                                               objects=va_objs)
        mock_va_get_all_by_vol.return_value = va_list
        self.assertEqual(va_list, volume.volume_attachment)
        mock_va_get_all_by_vol.assert_called_once_with(self.context, volume.id)

        # Test admin_metadata lazy-loaded field - user context
        adm_metadata = {'bar': 'foo'}
        mock_admin_metadata_get.return_value = adm_metadata
        self.assertEqual({}, volume.admin_metadata)
        self.assertFalse(mock_admin_metadata_get.called)

        # Test admin_metadata lazy-loaded field - admin context
        adm_context = self.context.elevated()
        volume = objects.Volume._from_db_object(adm_context, objects.Volume(),
                                                fake_volume.fake_db_volume())
        adm_metadata = {'bar': 'foo'}
        mock_admin_metadata_get.return_value = adm_metadata
        self.assertEqual(adm_metadata, volume.admin_metadata)
        mock_admin_metadata_get.assert_called_once_with(adm_context, volume.id)

    @mock.patch('cinder.objects.consistencygroup.ConsistencyGroup.get_by_id')
    def test_obj_load_attr_cgroup_not_exist(self, mock_cg_get_by_id):
        fake_db_volume = fake_volume.fake_db_volume(consistencygroup_id=None)
        volume = objects.Volume._from_db_object(
            self.context, objects.Volume(), fake_db_volume)

        self.assertIsNone(volume.consistencygroup)
        mock_cg_get_by_id.assert_not_called()

    @mock.patch('cinder.objects.group.Group.get_by_id')
    def test_obj_load_attr_group_not_exist(self, mock_group_get_by_id):
        fake_db_volume = fake_volume.fake_db_volume(group_id=None)
        volume = objects.Volume._from_db_object(
            self.context, objects.Volume(), fake_db_volume)

        self.assertIsNone(volume.group)
        mock_group_get_by_id.assert_not_called()

    def test_from_db_object_with_all_expected_attributes(self):
        expected_attrs = ['metadata', 'admin_metadata', 'glance_metadata',
                          'volume_type', 'volume_attachment',
                          'consistencygroup']

        db_metadata = [{'key': 'foo', 'value': 'bar'}]
        db_admin_metadata = [{'key': 'admin_foo', 'value': 'admin_bar'}]
        db_glance_metadata = [{'key': 'glance_foo', 'value': 'glance_bar'}]
        db_volume_type = fake_volume.fake_db_volume_type()
        db_volume_attachments = fake_volume.volume_attachment_db_obj()
        db_consistencygroup = fake_consistencygroup.fake_db_consistencygroup()
        db_snapshots = fake_snapshot.fake_db_snapshot()

        db_volume = fake_volume.fake_db_volume(
            volume_metadata=db_metadata,
            volume_admin_metadata=db_admin_metadata,
            volume_glance_metadata=db_glance_metadata,
            volume_type=db_volume_type,
            volume_attachment=[db_volume_attachments],
            consistencygroup=db_consistencygroup,
            snapshots=[db_snapshots],
        )
        volume = objects.Volume._from_db_object(self.context, objects.Volume(),
                                                db_volume, expected_attrs)

        self.assertEqual({'foo': 'bar'}, volume.metadata)
        self.assertEqual({'admin_foo': 'admin_bar'}, volume.admin_metadata)
        self.assertEqual({'glance_foo': 'glance_bar'}, volume.glance_metadata)
        self._compare(self, db_volume_type, volume.volume_type)
        self._compare(self, db_volume_attachments, volume.volume_attachment)
        self._compare(self, db_consistencygroup, volume.consistencygroup)
        self._compare(self, db_snapshots, volume.snapshots)

    @mock.patch('cinder.db.volume_glance_metadata_get', return_value={})
    @mock.patch('cinder.db.sqlalchemy.api.volume_get')
    def test_refresh(self, volume_get, volume_metadata_get):
        db_volume1 = fake_volume.fake_db_volume()
        db_volume2 = db_volume1.copy()
        db_volume2['display_name'] = 'foobar'

        # On the second volume_get, return the volume with an updated
        # display_name
        volume_get.side_effect = [db_volume1, db_volume2]
        volume = objects.Volume.get_by_id(self.context, fake.VOLUME_ID)
        self._compare(self, db_volume1, volume)

        # display_name was updated, so a volume refresh should have a new value
        # for that field
        volume.refresh()
        self._compare(self, db_volume2, volume)
        if six.PY3:
            call_bool = mock.call.__bool__()
        else:
            call_bool = mock.call.__nonzero__()
        volume_get.assert_has_calls([mock.call(self.context, fake.VOLUME_ID),
                                     call_bool,
                                     mock.call(self.context, fake.VOLUME_ID)])

    def test_metadata_aliases(self):
        volume = objects.Volume(context=self.context)
        # metadata<->volume_metadata
        volume.metadata = {'abc': 'def'}
        self.assertEqual([{'key': 'abc', 'value': 'def'}],
                         volume.volume_metadata)

        md = [{'key': 'def', 'value': 'abc'}]
        volume.volume_metadata = md
        self.assertEqual({'def': 'abc'}, volume.metadata)

        # admin_metadata<->volume_admin_metadata
        volume.admin_metadata = {'foo': 'bar'}
        self.assertEqual([{'key': 'foo', 'value': 'bar'}],
                         volume.volume_admin_metadata)

        volume.volume_admin_metadata = [{'key': 'xyz', 'value': '42'}]
        self.assertEqual({'xyz': '42'}, volume.admin_metadata)

        # glance_metadata<->volume_glance_metadata
        volume.glance_metadata = {'jkl': 'mno'}
        self.assertEqual([{'key': 'jkl', 'value': 'mno'}],
                         volume.volume_glance_metadata)

        volume.volume_glance_metadata = [{'key': 'prs', 'value': 'tuw'}]
        self.assertEqual({'prs': 'tuw'}, volume.glance_metadata)

    @mock.patch('cinder.db.volume_metadata_update', return_value={})
    @mock.patch('cinder.db.volume_update')
    @ddt.data({'src_vol_type_id': fake.VOLUME_TYPE_ID,
               'dest_vol_type_id': fake.VOLUME_TYPE2_ID},
              {'src_vol_type_id': None,
               'dest_vol_type_id': fake.VOLUME_TYPE2_ID})
    @ddt.unpack
    def test_finish_volume_migration(self, volume_update, metadata_update,
                                     src_vol_type_id, dest_vol_type_id):
        src_volume_db = fake_volume.fake_db_volume(
            **{'id': fake.VOLUME_ID, 'volume_type_id': src_vol_type_id})
        if src_vol_type_id:
            src_volume_db['volume_type'] = fake_volume.fake_db_volume_type(
                id=src_vol_type_id)
        dest_volume_db = fake_volume.fake_db_volume(
            **{'id': fake.VOLUME2_ID, 'volume_type_id': dest_vol_type_id})
        if dest_vol_type_id:
            dest_volume_db['volume_type'] = fake_volume.fake_db_volume_type(
                id=dest_vol_type_id)
        expected_attrs = objects.Volume._get_expected_attrs(self.context)
        src_volume = objects.Volume._from_db_object(
            self.context, objects.Volume(), src_volume_db,
            expected_attrs=expected_attrs)
        dest_volume = objects.Volume._from_db_object(
            self.context, objects.Volume(), dest_volume_db,
            expected_attrs=expected_attrs)
        updated_dest_volume = src_volume.finish_volume_migration(
            dest_volume)
        self.assertEqual('deleting', updated_dest_volume.migration_status)
        self.assertEqual('migration src for ' + src_volume.id,
                         updated_dest_volume.display_description)
        self.assertEqual(src_volume.id, updated_dest_volume._name_id)
        self.assertTrue(volume_update.called)
        volume_update.assert_has_calls([
            mock.call(self.context, src_volume.id, mock.ANY),
            mock.call(self.context, dest_volume.id, mock.ANY)])
        ctxt, vol_id, updates = volume_update.call_args[0]
        self.assertNotIn('volume_type', updates)

        # Ensure that the destination volume type has not been overwritten
        self.assertEqual(dest_vol_type_id,
                         getattr(updated_dest_volume, 'volume_type_id'))
        # Ignore these attributes, since they were updated by
        # finish_volume_migration
        ignore_keys = ('id', 'provider_location', '_name_id',
                       'migration_status', 'display_description', 'status',
                       'volume_glance_metadata', 'volume_type')

        dest_vol_dict = {k: updated_dest_volume[k] for k in
                         updated_dest_volume.keys() if k not in ignore_keys}
        src_vol_dict = {k: src_volume[k] for k in src_volume.keys()
                        if k not in ignore_keys}
        self.assertEqual(src_vol_dict, dest_vol_dict)

    def test_volume_with_metadata_serialize_deserialize_no_changes(self):
        updates = {'volume_glance_metadata': [{'key': 'foo', 'value': 'bar'}],
                   'expected_attrs': ['glance_metadata']}
        volume = fake_volume.fake_volume_obj(self.context, **updates)
        serializer = objects.base.CinderObjectSerializer()
        serialized_volume = serializer.serialize_entity(self.context, volume)
        volume = serializer.deserialize_entity(self.context, serialized_volume)
        self.assertDictEqual({}, volume.obj_get_changes())

    @mock.patch('cinder.db.volume_admin_metadata_update')
    @mock.patch('cinder.db.sqlalchemy.api.volume_attach')
    def test_begin_attach(self, volume_attach, metadata_update):
        volume = fake_volume.fake_volume_obj(self.context)
        db_attachment = fake_volume.volume_attachment_db_obj(
            volume_id=volume.id,
            attach_status=fields.VolumeAttachStatus.ATTACHING)
        volume_attach.return_value = db_attachment
        metadata_update.return_value = {'attached_mode': 'rw'}

        with mock.patch.object(self.context, 'elevated') as mock_elevated:
            mock_elevated.return_value = context.get_admin_context()
            attachment = volume.begin_attach("rw")
            self.assertIsInstance(attachment, objects.VolumeAttachment)
            self.assertEqual(volume.id, attachment.volume_id)
            self.assertEqual(fields.VolumeAttachStatus.ATTACHING,
                             attachment.attach_status)
            metadata_update.assert_called_once_with(self.context.elevated(),
                                                    volume.id,
                                                    {'attached_mode': u'rw'},
                                                    True)
            self.assertEqual('rw', volume.admin_metadata['attached_mode'])

    @mock.patch('cinder.db.volume_admin_metadata_delete')
    @mock.patch('cinder.db.sqlalchemy.api.volume_detached')
    @mock.patch('cinder.objects.volume_attachment.VolumeAttachmentList.'
                'get_all_by_volume_id')
    def test_volume_detached_with_attachment(
            self, volume_attachment_get,
            volume_detached,
            metadata_delete):
        va_objs = [objects.VolumeAttachment(context=self.context, id=i)
                   for i in [fake.OBJECT_ID, fake.OBJECT2_ID, fake.OBJECT3_ID]]
        # As changes are not saved, we need reset it here. Later changes
        # will be checked.
        for obj in va_objs:
            obj.obj_reset_changes()
        va_list = objects.VolumeAttachmentList(context=self.context,
                                               objects=va_objs)
        va_list.obj_reset_changes()
        volume_attachment_get.return_value = va_list
        admin_context = context.get_admin_context()
        volume = fake_volume.fake_volume_obj(
            admin_context,
            volume_attachment=va_list,
            volume_admin_metadata=[{'key': 'attached_mode',
                                    'value': 'rw'}])
        self.assertEqual(3, len(volume.volume_attachment))
        volume_detached.return_value = ({'status': 'in-use'},
                                        {'attached_mode': 'rw'})
        with mock.patch.object(admin_context, 'elevated') as mock_elevated:
            mock_elevated.return_value = admin_context
            volume.finish_detach(fake.OBJECT_ID)
            volume_detached.assert_called_once_with(admin_context,
                                                    volume.id,
                                                    fake.OBJECT_ID)
            metadata_delete.assert_called_once_with(admin_context,
                                                    volume.id,
                                                    'attached_mode')
            self.assertEqual('in-use', volume.status)
            self.assertEqual({}, volume.cinder_obj_get_changes())
            self.assertEqual(2, len(volume.volume_attachment))
            self.assertNotIn('attached_mode', volume.admin_metadata)

    @mock.patch('cinder.db.volume_admin_metadata_delete')
    @mock.patch('cinder.db.sqlalchemy.api.volume_detached')
    @mock.patch('cinder.objects.volume_attachment.VolumeAttachmentList.'
                'get_all_by_volume_id')
    def test_volume_detached_without_attachment(
            self, volume_attachment_get, volume_detached, metadata_delete):
        admin_context = context.get_admin_context()
        volume = fake_volume.fake_volume_obj(
            admin_context,
            volume_admin_metadata=[{'key': 'attached_mode',
                                    'value': 'rw'}])
        self.assertFalse(volume.obj_attr_is_set('volume_attachment'))
        volume_detached.return_value = ({'status': 'in-use'}, None)
        with mock.patch.object(admin_context, 'elevated') as mock_elevated:
            mock_elevated.return_value = admin_context
            volume.finish_detach(fake.OBJECT_ID)
            metadata_delete.assert_called_once_with(admin_context,
                                                    volume.id,
                                                    'attached_mode')
            volume_detached.assert_called_once_with(admin_context,
                                                    volume.id,
                                                    fake.OBJECT_ID)
            self.assertEqual('in-use', volume.status)
            self.assertEqual({}, volume.cinder_obj_get_changes())
            self.assertFalse(volume_attachment_get.called)

    @ddt.data('1.6', '1.7')
    def test_obj_make_compatible_cluster_added(self, version):
        extra_data = {'cluster_name': 'cluster_name',
                      'cluster': objects.Cluster()}
        volume = objects.Volume(self.context, host='host', **extra_data)

        serializer = ovo_base.CinderObjectSerializer(version)
        primitive = serializer.serialize_entity(self.context, volume)

        converted_volume = objects.Volume.obj_from_primitive(primitive)
        is_set = version == '1.7'
        for key in extra_data:
            self.assertEqual(is_set, converted_volume.obj_attr_is_set(key))
        self.assertEqual('host', converted_volume.host)

    @ddt.data('1.9', '1.10')
    def test_obj_make_compatible_groups_added(self, version):
        extra_data = {'group_id': fake.GROUP_ID,
                      'group': objects.Group()}
        volume = objects.Volume(self.context, host='host', **extra_data)

        serializer = ovo_base.CinderObjectSerializer(version)
        primitive = serializer.serialize_entity(self.context, volume)

        converted_volume = objects.Volume.obj_from_primitive(primitive)
        is_set = version == '1.10'
        for key in extra_data:
            self.assertEqual(is_set, converted_volume.obj_attr_is_set(key))
        self.assertEqual('host', converted_volume.host)

    @ddt.data(True, False)
    def test_is_replicated(self, result):
        volume_type = fake_volume.fake_volume_type_obj(self.context)
        volume = fake_volume.fake_volume_obj(
            self.context, volume_type_id=volume_type.id)
        volume.volume_type = volume_type
        with mock.patch.object(volume_type, 'is_replicated',
                               return_value=result) as is_replicated:
            self.assertEqual(result, volume.is_replicated())
            is_replicated.assert_called_once_with()

    def test_is_replicated_no_type(self):
        volume = fake_volume.fake_volume_obj(
            self.context, volume_type_id=None, volume_type=None)
        self.assertFalse(bool(volume.is_replicated()))


@ddt.ddt
class TestVolumeList(test_objects.BaseObjectsTestCase):
    @mock.patch('cinder.db.volume_get_all')
    def test_get_all(self, volume_get_all):
        db_volume = fake_volume.fake_db_volume()
        volume_get_all.return_value = [db_volume]

        volumes = objects.VolumeList.get_all(self.context,
                                             mock.sentinel.marker,
                                             mock.sentinel.limit,
                                             mock.sentinel.sort_key,
                                             mock.sentinel.sort_dir)
        self.assertEqual(1, len(volumes))
        TestVolume._compare(self, db_volume, volumes[0])

    @mock.patch('cinder.db.volume_get_all_by_host')
    def test_get_by_host(self, get_all_by_host):
        db_volume = fake_volume.fake_db_volume()
        get_all_by_host.return_value = [db_volume]

        volumes = objects.VolumeList.get_all_by_host(
            self.context, 'fake-host')
        self.assertEqual(1, len(volumes))
        TestVolume._compare(self, db_volume, volumes[0])

    @mock.patch('cinder.db.volume_get_all_by_group')
    def test_get_by_group(self, get_all_by_group):
        db_volume = fake_volume.fake_db_volume()
        get_all_by_group.return_value = [db_volume]

        volumes = objects.VolumeList.get_all_by_group(
            self.context, 'fake-host')
        self.assertEqual(1, len(volumes))
        TestVolume._compare(self, db_volume, volumes[0])

    @mock.patch('cinder.db.volume_get_all_by_project')
    def test_get_by_project(self, get_all_by_project):
        db_volume = fake_volume.fake_db_volume()
        get_all_by_project.return_value = [db_volume]

        volumes = objects.VolumeList.get_all_by_project(
            self.context, mock.sentinel.project_id, mock.sentinel.marker,
            mock.sentinel.limit, mock.sentinel.sorted_keys,
            mock.sentinel.sorted_dirs, mock.sentinel.filters)
        self.assertEqual(1, len(volumes))
        TestVolume._compare(self, db_volume, volumes[0])

    @ddt.data(['name_id'], ['__contains__'])
    def test_get_by_project_with_sort_key(self, sort_keys):
        fake_volume.fake_db_volume()

        self.assertRaises(exception.InvalidInput,
                          objects.VolumeList.get_all_by_project,
                          self.context,
                          self.context.project_id,
                          sort_keys=sort_keys)

    @mock.patch('cinder.db.volume_include_in_cluster')
    def test_include_in_cluster(self, include_mock):
        filters = {'host': mock.sentinel.host,
                   'cluster_name': mock.sentinel.cluster_name}
        cluster = 'new_cluster'
        objects.VolumeList.include_in_cluster(self.context, cluster, **filters)
        include_mock.assert_called_once_with(self.context, cluster, True,
                                             **filters)

    @mock.patch('cinder.db.volume_include_in_cluster')
    def test_include_in_cluster_specify_partial(self, include_mock):
        filters = {'host': mock.sentinel.host,
                   'cluster_name': mock.sentinel.cluster_name}
        cluster = 'new_cluster'
        objects.VolumeList.include_in_cluster(self.context, cluster,
                                              mock.sentinel.partial_rename,
                                              **filters)
        include_mock.assert_called_once_with(self.context, cluster,
                                             mock.sentinel.partial_rename,
                                             **filters)
