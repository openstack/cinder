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

from unittest import mock

import ddt
from sqlalchemy.orm import attributes

from cinder import db
from cinder import objects
from cinder.objects import fields
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_volume
from cinder.tests.unit import objects as test_objects


@ddt.ddt
class TestVolumeAttachment(test_objects.BaseObjectsTestCase):

    @mock.patch('cinder.db.sqlalchemy.api.volume_attachment_get')
    def test_get_by_id(self, volume_attachment_get):
        db_attachment = fake_volume.volume_attachment_db_obj()
        attachment_obj = fake_volume.volume_attachment_ovo(self.context)
        volume_attachment_get.return_value = db_attachment
        attachment = objects.VolumeAttachment.get_by_id(self.context,
                                                        fake.ATTACHMENT_ID)
        self._compare(self, attachment_obj, attachment)

    @mock.patch.object(objects.Volume, 'get_by_id')
    def test_lazy_load_volume(self, volume_get_mock):
        volume = objects.Volume(self.context, id=fake.VOLUME_ID)
        volume_get_mock.return_value = volume
        attach = objects.VolumeAttachment(self.context, id=fake.ATTACHMENT_ID,
                                          volume_id=volume.id)

        r = attach.volume
        self.assertEqual(volume, r)
        volume_get_mock.assert_called_once_with(self.context, volume.id)

    def test_from_db_object_no_volume(self):
        original_get = attributes.InstrumentedAttribute.__get__

        def my_get(get_self, instance, owner):
            self.assertNotEqual('volume', get_self.key)
            return original_get(get_self, instance, owner)

        # Volume field is not loaded
        attach = fake_volume.models.VolumeAttachment(id=fake.ATTACHMENT_ID,
                                                     volume_id=fake.VOLUME_ID)
        patch_str = 'sqlalchemy.orm.attributes.InstrumentedAttribute.__get__'
        with mock.patch(patch_str, side_effect=my_get):
            objects.VolumeAttachment._from_db_object(
                self.context, objects.VolumeAttachment(), attach)

    @mock.patch('cinder.db.volume_attachment_update')
    def test_save(self, volume_attachment_update):
        attachment = fake_volume.volume_attachment_ovo(self.context)
        attachment.attach_status = fields.VolumeAttachStatus.ATTACHING
        attachment.save()
        volume_attachment_update.assert_called_once_with(
            self.context, attachment.id,
            {'attach_status': fields.VolumeAttachStatus.ATTACHING})

    @mock.patch('cinder.db.sqlalchemy.api.volume_attachment_get')
    def test_refresh(self, attachment_get):
        db_attachment1 = fake_volume.volume_attachment_db_obj()
        attachment_obj1 = fake_volume.volume_attachment_ovo(self.context)
        db_attachment2 = fake_volume.volume_attachment_db_obj()
        db_attachment2.mountpoint = '/dev/sdc'
        attachment_obj2 = fake_volume.volume_attachment_ovo(
            self.context, mountpoint='/dev/sdc')

        # On the second volume_attachment_get, return the volume attachment
        # with an updated mountpoint
        attachment_get.side_effect = [db_attachment1, db_attachment2]
        attachment = objects.VolumeAttachment.get_by_id(self.context,
                                                        fake.ATTACHMENT_ID)
        self._compare(self, attachment_obj1, attachment)

        # mountpoint was updated, so a volume attachment refresh should have a
        # new value for that field
        attachment.refresh()
        self._compare(self, attachment_obj2, attachment)
        attachment_get.assert_has_calls([mock.call(self.context,
                                                   fake.ATTACHMENT_ID),
                                         mock.call.__bool__(),
                                         mock.call(self.context,
                                                   fake.ATTACHMENT_ID)])

    @mock.patch('cinder.db.sqlalchemy.api.volume_attached')
    def test_volume_attached(self, volume_attached):
        attachment = fake_volume.volume_attachment_ovo(self.context)
        updated_values = {'mountpoint': '/dev/sda',
                          'attach_status': fields.VolumeAttachStatus.ATTACHED,
                          'instance_uuid': fake.INSTANCE_ID}
        volume_attached.return_value = (fake_volume.fake_db_volume(),
                                        updated_values)
        volume = attachment.finish_attach(fake.INSTANCE_ID,
                                          'fake_host',
                                          '/dev/sda',
                                          'rw')
        self.assertIsInstance(volume, objects.Volume)
        volume_attached.assert_called_once_with(mock.ANY,
                                                attachment.id,
                                                fake.INSTANCE_ID,
                                                'fake_host',
                                                '/dev/sda',
                                                'rw',
                                                True)
        self.assertEqual('/dev/sda', attachment.mountpoint)
        self.assertEqual(fake.INSTANCE_ID, attachment.instance_uuid)
        self.assertEqual(fields.VolumeAttachStatus.ATTACHED,
                         attachment.attach_status)

    def test_migrate_attachment_specs(self):
        # Create an attachment.
        attachment = objects.VolumeAttachment(
            self.context, attach_status='attaching', volume_id=fake.VOLUME_ID)
        attachment.create()
        # Create some attachment_specs. Note that the key and value have to
        # be strings, the table doesn't handle things like a wwpns list
        # for a fibrechannel connector.
        connector = {'host': '127.0.0.1'}
        db.attachment_specs_update_or_create(
            self.context, attachment.id, connector)
        # Now get the volume attachment object from the database and make
        # sure the connector was migrated from the attachment_specs table
        # to the volume_attachment table and the specs were deleted.
        attachment = objects.VolumeAttachment.get_by_id(
            self.context, attachment.id)
        self.assertIn('connector', attachment)
        self.assertDictEqual(connector, attachment.connector)
        self.assertEqual(0, len(db.attachment_specs_get(
            self.context, attachment.id)))
        # Make sure we can store a fibrechannel type connector that has a wwpns
        # list value.
        connector['wwpns'] = ['21000024ff34c92d', '21000024ff34c92c']
        attachment.connector = connector
        attachment.save()
        # Get the object from the DB again and make sure the connector is
        # there.
        attachment = objects.VolumeAttachment.get_by_id(
            self.context, attachment.id)
        self.assertIn('connector', attachment)
        self.assertDictEqual(connector, attachment.connector)


class TestVolumeAttachmentList(test_objects.BaseObjectsTestCase):
    @mock.patch('cinder.db.volume_attachment_get_all_by_volume_id')
    def test_get_all_by_volume_id(self, get_used_by_volume_id):
        db_attachment = fake_volume.volume_attachment_db_obj()
        get_used_by_volume_id.return_value = [db_attachment]
        attachment_obj = fake_volume.volume_attachment_ovo(self.context)

        attachments = objects.VolumeAttachmentList.get_all_by_volume_id(
            self.context, mock.sentinel.volume_id)

        self.assertEqual(1, len(attachments))
        self._compare(self, attachment_obj, attachments[0])

    @mock.patch('cinder.db.volume_attachment_get_all_by_host')
    def test_get_all_by_host(self, get_by_host):
        db_attachment = fake_volume.volume_attachment_db_obj()
        attachment_obj = fake_volume.volume_attachment_ovo(self.context)
        get_by_host.return_value = [db_attachment]

        attachments = objects.VolumeAttachmentList.get_all_by_host(
            self.context, mock.sentinel.host)
        self.assertEqual(1, len(attachments))
        self._compare(self, attachment_obj, attachments[0])

    @mock.patch('cinder.db.volume_attachment_get_all_by_instance_uuid')
    def test_get_all_by_instance_uuid(self, get_by_instance_uuid):
        db_attachment = fake_volume.volume_attachment_db_obj()
        get_by_instance_uuid.return_value = [db_attachment]
        attachment_obj = fake_volume.volume_attachment_ovo(self.context)

        attachments = objects.VolumeAttachmentList.get_all_by_instance_uuid(
            self.context, mock.sentinel.uuid)
        self.assertEqual(1, len(attachments))
        self._compare(self, attachment_obj, attachments[0])
