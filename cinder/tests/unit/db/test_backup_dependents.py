# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import sqlalchemy as sa

from cinder import context
from cinder.db import api as db
from cinder.db import models
from cinder.tests.unit import test
from cinder.tests.unit import utils as tests_utils


class BackupDependentsTestCase(test.TestCase):
    """Tests for db.backup_add_dependent()/backup_remove_dependent()."""

    def setUp(self):
        super().setUp()
        self.ctxt = context.get_admin_context()

    def _raw_counter(self, backup_id):
        """Read the column directly; the object layer maps NULL to 0."""
        with db.get_engine().connect() as conn:
            return conn.execute(
                sa.select(models.Backup.num_dependent_backups).where(
                    models.Backup.id == backup_id)).first()[0]

    def _backup_with_dependents(self, count):
        """Create a backup whose counter is set to count.

        The counter is written directly rather than by calling the functions
        under test, so that a test is never set up by the very thing it is
        meant to be checking.
        """
        backup = tests_utils.create_backup(self.ctxt)
        with db.get_engine().begin() as conn:
            conn.execute(
                sa.update(models.Backup)
                .where(models.Backup.id == backup.id)
                .values(num_dependent_backups=count))
        return backup

    def _capture_backup_updates(self):
        """Collect the UPDATE statements issued against the backups table."""
        statements = []

        def record(conn, cursor, statement, params, context, executemany):
            if statement.lstrip().upper().startswith('UPDATE BACKUPS'):
                statements.append(statement)

        sa.event.listen(sa.engine.Engine, 'before_cursor_execute', record)
        self.addCleanup(sa.event.remove, sa.engine.Engine,
                        'before_cursor_execute', record)
        return statements

    def test_new_backup_counter_starts_at_zero(self):
        # The model default applies at insert time, so newly created backups
        # start at 0 rather than NULL.
        backup = tests_utils.create_backup(self.ctxt)

        self.assertEqual(0, self._raw_counter(backup.id))

    def test_add_from_null(self):
        # The model default only fires on insert, so rows written before it
        # existed still hold NULL. NULL + 1 is NULL, so the increment has to
        # coalesce or the first dependent of an existing backup would
        # silently fail to register.
        backup = self._backup_with_dependents(None)

        db.backup_add_dependent(self.ctxt, backup.id)

        self.assertEqual(1, self._raw_counter(backup.id))

    def test_add_accumulates(self):
        backup = self._backup_with_dependents(1)

        db.backup_add_dependent(self.ctxt, backup.id)

        self.assertEqual(2, self._raw_counter(backup.id))

    def test_remove(self):
        backup = self._backup_with_dependents(2)

        db.backup_remove_dependent(self.ctxt, backup.id)

        self.assertEqual(1, self._raw_counter(backup.id))

    def test_remove_floors_at_zero(self):
        backup = self._backup_with_dependents(0)

        db.backup_remove_dependent(self.ctxt, backup.id)

        self.assertEqual(0, self._raw_counter(backup.id))

    def test_remove_leaves_null_alone(self):
        backup = self._backup_with_dependents(None)

        db.backup_remove_dependent(self.ctxt, backup.id)

        self.assertIsNone(self._raw_counter(backup.id))

    def test_adjust_is_atomic(self):
        """The new value has to be computed by the database.

        Every other test here runs serially, and a serial test cannot tell
        an atomic UPDATE from the read-modify-write cycle that caused the
        bug: both land on the same number. Only the shape of the emitted
        statement distinguishes them, so assert on that, or a later refactor
        could reintroduce the race with a green gate.
        """
        backup = self._backup_with_dependents(1)
        statements = self._capture_backup_updates()

        db.backup_remove_dependent(self.ctxt, backup.id)

        self.assertEqual(1, len(statements))
        # The right hand side of the assignment must reference the column
        # itself, not a value the caller read beforehand.
        assignment = statements[0].split('SET', 1)[1].split('WHERE', 1)[0]
        self.assertIn('coalesce(backups.num_dependent_backups',
                      assignment.lower())

    def test_remove_floor_is_atomic(self):
        """The refusal to go negative has to be done by the database too."""
        backup = self._backup_with_dependents(0)
        statements = self._capture_backup_updates()

        db.backup_remove_dependent(self.ctxt, backup.id)

        # One statement that both tests and applies the decrement, rather
        # than a read followed by a conditional write.
        self.assertEqual(1, len(statements))
        condition = statements[0].split('WHERE', 1)[1].lower()
        self.assertIn('coalesce(backups.num_dependent_backups', condition)
