# Copyright (C) 2015 OpenStack Foundation
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

"""Tests for db purge."""

import datetime
import uuid

from oslo_utils import timeutils

from cinder import context
from cinder import db
from cinder.db.sqlalchemy import api as db_api
from cinder import exception
from cinder import test

from oslo_db.sqlalchemy import utils as sqlalchemyutils


class PurgeDeletedTest(test.TestCase):

    def setUp(self):
        super(PurgeDeletedTest, self).setUp()
        self.context = context.get_admin_context()
        self.engine = db_api.get_engine()
        self.session = db_api.get_session()
        self.conn = self.engine.connect()
        self.volumes = sqlalchemyutils.get_table(
            self.engine, "volumes")
        # The volume_metadata table has a FK of volume_id
        self.vm = sqlalchemyutils.get_table(
            self.engine, "volume_metadata")
        self.uuidstrs = []
        for unused in range(6):
            self.uuidstrs.append(uuid.uuid4().hex)
        # Add 6 rows to table
        for uuidstr in self.uuidstrs:
            ins_stmt = self.volumes.insert().values(id=uuidstr)
            self.conn.execute(ins_stmt)
            ins_stmt = self.vm.insert().values(volume_id=uuidstr)
            self.conn.execute(ins_stmt)
        # Set 4 of them deleted, 2 are 60 days ago, 2 are 20 days ago
        old = timeutils.utcnow() - datetime.timedelta(days=20)
        older = timeutils.utcnow() - datetime.timedelta(days=60)
        make_old = self.volumes.update().\
            where(self.volumes.c.id.in_(self.uuidstrs[1:3]))\
            .values(deleted_at=old)
        make_older = self.volumes.update().\
            where(self.volumes.c.id.in_(self.uuidstrs[4:6]))\
            .values(deleted_at=older)
        make_meta_old = self.vm.update().\
            where(self.vm.c.volume_id.in_(self.uuidstrs[1:3]))\
            .values(deleted_at=old)
        make_meta_older = self.vm.update().\
            where(self.vm.c.volume_id.in_(self.uuidstrs[4:6]))\
            .values(deleted_at=older)
        self.conn.execute(make_old)
        self.conn.execute(make_older)
        self.conn.execute(make_meta_old)
        self.conn.execute(make_meta_older)

    def test_purge_deleted_rows_old(self):
        # Purge at 30 days old, should only delete 2 rows
        db.purge_deleted_rows(self.context, age_in_days=30)
        rows = self.session.query(self.volumes).count()
        meta_rows = self.session.query(self.vm).count()
        # Verify that we only deleted 2
        self.assertEqual(4, rows)
        self.assertEqual(4, meta_rows)

    def test_purge_deleted_rows_older(self):
        # Purge at 10 days old now, should delete 2 more rows
        db.purge_deleted_rows(self.context, age_in_days=10)
        rows = self.session.query(self.volumes).count()
        meta_rows = self.session.query(self.vm).count()
        # Verify that we only have 2 rows now
        self.assertEqual(2, rows)
        self.assertEqual(2, meta_rows)

    def test_purge_deleted_rows_bad_args(self):
        # Test with no age argument
        self.assertRaises(TypeError, db.purge_deleted_rows, self.context)
        # Test purge with non-integer
        self.assertRaises(exception.InvalidParameterValue,
                          db.purge_deleted_rows, self.context,
                          age_in_days='ten')
        # Test with negative value
        self.assertRaises(exception.InvalidParameterValue,
                          db.purge_deleted_rows, self.context,
                          age_in_days=-1)
