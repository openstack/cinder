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

from cinder import objects
from cinder.tests.unit import fake_volume
from cinder.tests.unit import objects as test_objects


class TestVolumeAttachment(test_objects.BaseObjectsTestCase):
    @staticmethod
    def _compare(test, db, obj):
        for field, value in db.items():
            test.assertEqual(db[field], obj[field])

    @mock.patch('cinder.db.volume_attachment_get')
    def test_get_by_id(self, volume_attachment_get):
        db_attachment = fake_volume.fake_db_volume_attachment()
        volume_attachment_get.return_value = db_attachment
        attachment = objects.VolumeAttachment.get_by_id(self.context, '1')
        self._compare(self, db_attachment, attachment)

    @mock.patch('cinder.db.volume_attachment_update')
    def test_save(self, volume_attachment_update):
        attachment = fake_volume.fake_volume_attachment_obj(self.context)
        attachment.attach_status = 'attaching'
        attachment.save()
        volume_attachment_update.assert_called_once_with(
            self.context, attachment.id, {'attach_status': 'attaching'})


class TestVolumeAttachmentList(test_objects.BaseObjectsTestCase):
    @mock.patch('cinder.db.volume_attachment_get_used_by_volume_id')
    def test_get_all_by_volume_id(self, get_used_by_volume_id):
        db_attachment = fake_volume.fake_db_volume_attachment()
        get_used_by_volume_id.return_value = [db_attachment]

        attachments = objects.VolumeAttachmentList.get_all_by_volume_id(
            self.context, mock.sentinel.volume_id)
        self.assertEqual(1, len(attachments))
        TestVolumeAttachment._compare(self, db_attachment, attachments[0])

    @mock.patch('cinder.db.volume_attachment_get_by_host')
    def test_get_all_by_host(self, get_by_host):
        db_attachment = fake_volume.fake_db_volume_attachment()
        get_by_host.return_value = [db_attachment]

        attachments = objects.VolumeAttachmentList.get_all_by_host(
            self.context, mock.sentinel.volume_id, mock.sentinel.host)
        self.assertEqual(1, len(attachments))
        TestVolumeAttachment._compare(self, db_attachment, attachments[0])

    @mock.patch('cinder.db.volume_attachment_get_by_instance_uuid')
    def test_get_all_by_instance_uuid(self, get_by_instance_uuid):
        db_attachment = fake_volume.fake_db_volume_attachment()
        get_by_instance_uuid.return_value = [db_attachment]

        attachments = objects.VolumeAttachmentList.get_all_by_instance_uuid(
            self.context, mock.sentinel.volume_id, mock.sentinel.uuid)
        self.assertEqual(1, len(attachments))
        TestVolumeAttachment._compare(self, db_attachment, attachments[0])
