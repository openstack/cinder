# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
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
"""Tests for Volume usage audit feature."""

import datetime

from cinder import context
from cinder import db
from cinder import objects
from cinder.objects import fields
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import volume as base


class GetActiveByWindowTestCase(base.BaseVolumeTestCase):
    def setUp(self):
        super(GetActiveByWindowTestCase, self).setUp()
        self.ctx = context.get_admin_context(read_deleted="yes")
        self.db_vol_attrs = [
            {
                'id': fake.VOLUME_ID,
                'host': 'devstack',
                'project_id': fake.PROJECT_ID,
                'created_at': datetime.datetime(1, 1, 1, 1, 1, 1),
                'deleted': True, 'status': 'deleted',
                'deleted_at': datetime.datetime(1, 2, 1, 1, 1, 1),
            },
            {
                'id': fake.VOLUME2_ID,
                'host': 'devstack',
                'project_id': fake.PROJECT_ID,
                'created_at': datetime.datetime(1, 1, 1, 1, 1, 1),
                'deleted': True, 'status': 'deleted',
                'deleted_at': datetime.datetime(1, 3, 10, 1, 1, 1),
            },
            {
                'id': fake.VOLUME3_ID,
                'host': 'devstack',
                'project_id': fake.PROJECT_ID,
                'created_at': datetime.datetime(1, 1, 1, 1, 1, 1),
                'deleted': True, 'status': 'deleted',
                'deleted_at': datetime.datetime(1, 5, 1, 1, 1, 1),
            },
            {
                'id': fake.VOLUME4_ID,
                'host': 'devstack',
                'project_id': fake.PROJECT_ID,
                'created_at': datetime.datetime(1, 3, 10, 1, 1, 1),
            },
            {
                'id': fake.VOLUME5_ID,
                'host': 'devstack',
                'project_id': fake.PROJECT_ID,
                'created_at': datetime.datetime(1, 5, 1, 1, 1, 1),
            }
        ]

        self.db_snap_attrs = [
            {
                'id': fake.SNAPSHOT_ID,
                'project_id': 'p1',
                'created_at': datetime.datetime(1, 1, 1, 1, 1, 1),
                'deleted': True,
                'status': fields.SnapshotStatus.DELETED,
                'deleted_at': datetime.datetime(1, 2, 1, 1, 1, 1),
                'volume_id': fake.VOLUME_ID,
            },

            {
                'id': fake.SNAPSHOT2_ID,
                'project_id': 'p1',
                'created_at': datetime.datetime(1, 1, 1, 1, 1, 1),
                'deleted': True,
                'status': fields.SnapshotStatus.DELETED,
                'deleted_at': datetime.datetime(1, 3, 10, 1, 1, 1),
                'volume_id': fake.VOLUME_ID,
            },
            {
                'id': fake.SNAPSHOT3_ID,
                'project_id': 'p1',
                'created_at': datetime.datetime(1, 1, 1, 1, 1, 1),
                'deleted': True,
                'status': fields.SnapshotStatus.DELETED,
                'deleted_at': datetime.datetime(1, 5, 1, 1, 1, 1),
                'volume_id': fake.VOLUME_ID,
            },
            {
                'id': fake.SNAPSHOT_ID,
                'project_id': 'p1',
                'created_at': datetime.datetime(1, 3, 10, 1, 1, 1),
                'volume_id': fake.VOLUME_ID,
            },
            {
                'id': fake.SNAPSHOT2_ID,
                'project_id': 'p1',
                'created_at': datetime.datetime(1, 5, 1, 1, 1, 1),
                'volume_id': fake.VOLUME_ID
            }
        ]

        self.db_back_attrs = [
            {
                'id': fake.BACKUP_ID,
                'host': 'devstack',
                'project_id': fake.PROJECT_ID,
                'created_at': datetime.datetime(1, 1, 1, 1, 1, 1),
                'deleted': 1,
                'status': 'deleted',
                'deleted_at': datetime.datetime(1, 2, 1, 1, 1, 1)
            },
            {
                'id': fake.BACKUP2_ID,
                'host': 'devstack',
                'project_id': fake.PROJECT_ID,
                'created_at': datetime.datetime(1, 1, 1, 1, 1, 1),
                'deleted': 1,
                'status': 'deleted',
                'deleted_at': datetime.datetime(1, 3, 10, 1, 1, 1)
            },
            {
                'id': fake.BACKUP3_ID,
                'host': 'devstack',
                'project_id': fake.PROJECT_ID,
                'created_at': datetime.datetime(1, 1, 1, 1, 1, 1),
                'deleted': 1,
                'status': 'deleted',
                'deleted_at': datetime.datetime(1, 5, 1, 1, 1, 1)
            },
            {
                'id': fake.BACKUP4_ID,
                'host': 'devstack',
                'project_id': fake.PROJECT_ID,
                'created_at': datetime.datetime(1, 3, 10, 1, 1, 1),
            },
            {
                'id': fake.BACKUP5_ID,
                'host': 'devstack',
                'project_id': fake.PROJECT_ID,
                'created_at': datetime.datetime(1, 5, 1, 1, 1, 1),
            },
        ]

    def test_volume_get_all_active_by_window(self):
        # Find all all volumes valid within a timeframe window.

        # Not in window
        db.volume_create(self.ctx, self.db_vol_attrs[0])

        # In - deleted in window
        db.volume_create(self.ctx, self.db_vol_attrs[1])

        # In - deleted after window
        db.volume_create(self.ctx, self.db_vol_attrs[2])

        # In - created in window
        db.volume_create(self.context, self.db_vol_attrs[3])

        # Not of window.
        db.volume_create(self.context, self.db_vol_attrs[4])

        volumes = db.volume_get_all_active_by_window(
            self.context,
            datetime.datetime(1, 3, 1, 1, 1, 1),
            datetime.datetime(1, 4, 1, 1, 1, 1),
            project_id=fake.PROJECT_ID)
        self.assertEqual(3, len(volumes))
        self.assertEqual(fake.VOLUME2_ID, volumes[0].id)
        self.assertEqual(fake.VOLUME3_ID, volumes[1].id)
        self.assertEqual(fake.VOLUME4_ID, volumes[2].id)

    def test_snapshot_get_all_active_by_window(self):
        # Find all all snapshots valid within a timeframe window.
        db.volume_create(self.context, {'id': fake.VOLUME_ID})
        for i in range(5):
            self.db_vol_attrs[i]['volume_id'] = fake.VOLUME_ID

        # Not in window
        del self.db_snap_attrs[0]['id']
        snap1 = objects.Snapshot(self.ctx, **self.db_snap_attrs[0])
        snap1.create()

        # In - deleted in window
        del self.db_snap_attrs[1]['id']
        snap2 = objects.Snapshot(self.ctx, **self.db_snap_attrs[1])
        snap2.create()

        # In - deleted after window
        del self.db_snap_attrs[2]['id']
        snap3 = objects.Snapshot(self.ctx, **self.db_snap_attrs[2])
        snap3.create()

        # In - created in window
        del self.db_snap_attrs[3]['id']
        snap4 = objects.Snapshot(self.ctx, **self.db_snap_attrs[3])
        snap4.create()

        # Not of window.
        del self.db_snap_attrs[4]['id']
        snap5 = objects.Snapshot(self.ctx, **self.db_snap_attrs[4])
        snap5.create()

        snapshots = objects.SnapshotList.get_all_active_by_window(
            self.context,
            datetime.datetime(1, 3, 1, 1, 1, 1),
            datetime.datetime(1, 4, 1, 1, 1, 1)).objects
        self.assertEqual(3, len(snapshots))
        self.assertEqual(snap2.id, snapshots[0].id)
        self.assertEqual(fake.VOLUME_ID, snapshots[0].volume_id)
        self.assertEqual(snap3.id, snapshots[1].id)
        self.assertEqual(fake.VOLUME_ID, snapshots[1].volume_id)
        self.assertEqual(snap4.id, snapshots[2].id)
        self.assertEqual(fake.VOLUME_ID, snapshots[2].volume_id)

    def test_backup_get_all_active_by_window(self):
        # Find all backups valid within a timeframe window.
        db.volume_create(self.context, {'id': fake.VOLUME_ID})
        for i in range(5):
            self.db_back_attrs[i]['volume_id'] = fake.VOLUME_ID

        # Not in window
        db.backup_create(self.ctx, self.db_back_attrs[0])

        # In - deleted in window
        db.backup_create(self.ctx, self.db_back_attrs[1])

        # In - deleted after window
        db.backup_create(self.ctx, self.db_back_attrs[2])

        # In - created in window
        db.backup_create(self.ctx, self.db_back_attrs[3])

        # Not of window
        db.backup_create(self.ctx, self.db_back_attrs[4])

        backups = db.backup_get_all_active_by_window(
            self.context,
            datetime.datetime(1, 3, 1, 1, 1, 1),
            datetime.datetime(1, 4, 1, 1, 1, 1),
            project_id=fake.PROJECT_ID
        )
        self.assertEqual(3, len(backups))
        self.assertEqual(fake.BACKUP2_ID, backups[0].id)
        self.assertEqual(fake.BACKUP3_ID, backups[1].id)
        self.assertEqual(fake.BACKUP4_ID, backups[2].id)
