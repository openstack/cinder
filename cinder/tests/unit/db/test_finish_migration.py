# Copyright 2013 IBM Corp.
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

"""Tests for finish_volume_migration."""


from cinder import context
from cinder import db
from cinder import objects
from cinder import test
from cinder.tests.unit import utils as testutils


class FinishVolumeMigrationTestCase(test.TestCase):
    """Test cases for finish_volume_migration."""

    def test_finish_volume_migration_no_volume_type(self):
        self._test_finish_volume_migration()

    def test_finish_volume_migration_with_volume_type(self):
        source_type = {'name': 'old', 'extra_specs': {}}
        dest_type = {'name': 'new', 'extra_specs': {}}
        self._test_finish_volume_migration(source_type=source_type,
                                           dest_type=dest_type)

    def test_finish_volume_migration_none_to_volume_type(self):
        dest_type = {'name': 'new', 'extra_specs': {}}
        self._test_finish_volume_migration(dest_type=dest_type)

    def _test_finish_volume_migration(self, source_type=None, dest_type=None):
        ctxt = context.RequestContext(user_id='user_id',
                                      project_id='project_id',
                                      is_admin=True)
        source_type_id = None
        dest_type_id = None
        if source_type:
            source_type_id = db.volume_type_create(ctxt, source_type).id
        if dest_type:
            dest_type_id = db.volume_type_create(ctxt, dest_type).id

        src_volume = testutils.create_volume(ctxt, host='src',
                                             migration_status='migrating',
                                             status='available',
                                             volume_type_id=source_type_id)
        dest_volume = testutils.create_volume(ctxt, host='dest',
                                              migration_status='target:fake',
                                              status='available',
                                              volume_type_id=dest_type_id)
        db.finish_volume_migration(ctxt, src_volume.id, dest_volume.id)

        # Check that we have copied destination volume DB data into source DB
        # entry so we can keep the id
        src_volume = objects.Volume.get_by_id(ctxt, src_volume.id)
        self.assertEqual('dest', src_volume.host)
        self.assertEqual('available', src_volume.status)
        self.assertIsNone(src_volume.migration_status)
        if dest_type:
            self.assertEqual(dest_type_id, src_volume.volume_type_id)
        else:
            self.assertIsNone(src_volume.volume_type_id)

        # Check that we have copied source volume DB data into destination DB
        # entry and we are setting it to deleting
        dest_volume = objects.Volume.get_by_id(ctxt, dest_volume.id)
        self.assertEqual('src', dest_volume.host)
        self.assertEqual('deleting', dest_volume.status)
        self.assertEqual('deleting', dest_volume.migration_status)
        if source_type:
            self.assertEqual(source_type_id, dest_volume.volume_type_id)
        else:
            self.assertIsNone(dest_volume.volume_type_id)
