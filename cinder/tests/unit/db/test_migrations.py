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

"""
Tests for database migrations. For each database backend supported by cinder,
the test case runs a series of test cases to ensure that migrations work
properly and that no data loss occurs if possible.
"""

from alembic import command as alembic_api
from alembic import script as alembic_script
import fixtures
from oslo_db.sqlalchemy import enginefacade
from oslo_db.sqlalchemy import test_fixtures
from oslo_db.sqlalchemy import test_migrations
from oslo_db.sqlalchemy import utils as db_utils
from oslo_log.fixture import logging_error as log_fixture
from oslotest import base as test_base
import sqlalchemy

from cinder.db import migration
from cinder.db.sqlalchemy import api
from cinder.db.sqlalchemy import models
from cinder.tests import fixtures as cinder_fixtures


class CinderModelsMigrationsSync(test_migrations.ModelsMigrationsSync):
    """Test sqlalchemy-migrate migrations."""

    # Migrations can take a long time, particularly on underpowered CI nodes.
    # Give them some breathing room.
    TIMEOUT_SCALING_FACTOR = 4

    def setUp(self):
        # Ensure BaseTestCase's ConfigureLogging fixture is disabled since
        # we're using our own (StandardLogging).
        with fixtures.EnvironmentVariable('OS_LOG_CAPTURE', '0'):
            super().setUp()

        self.useFixture(log_fixture.get_logging_handle_error_fixture())
        self.useFixture(cinder_fixtures.WarningsFixture())
        self.useFixture(cinder_fixtures.StandardLogging())

        self.engine = enginefacade.writer.get_engine()
        self.patch(api, 'get_engine', self.get_engine)

    def db_sync(self, engine):
        migration.db_sync(engine=self.engine)

    def get_engine(self):
        return self.engine

    def get_metadata(self):
        return models.BASE.metadata

    def filter_metadata_diff(self, diff):
        # Overriding the parent method to decide on certain attributes
        # that maybe present in the DB but not in the models.py

        def include_element(element):
            """Determine whether diff element should be excluded."""
            if element[0] == 'modify_nullable':
                table_name, column = element[2], element[3]
                return (table_name, column) not in {
                    # NOTE(stephenfin): This field has nullable=True set, but
                    # since it's also a primary key (primary_key=True) the
                    # resulting schema will still end up being "NOT NULL". This
                    # weird combination was deemed necessary because MySQL will
                    # otherwise set this to "NOT NULL DEFAULT ''" which may be
                    # harmless but is inconsistent with other models. See the
                    # migration for more information.
                    ('encryption', 'encryption_id'),
                    # NOTE(stephenfin): The nullability of these fields is
                    # dependent on the backend, for some reason
                    ('encryption', 'provider'),
                    ('encryption', 'control_location'),
                }

            return True

        return [element for element in diff if include_element(element[0])]


class TestModelsSyncSQLite(
    CinderModelsMigrationsSync,
    test_fixtures.OpportunisticDBTestMixin,
    test_base.BaseTestCase,
):
    pass


class TestModelsSyncMySQL(
    CinderModelsMigrationsSync,
    test_fixtures.OpportunisticDBTestMixin,
    test_base.BaseTestCase,
):
    FIXTURE = test_fixtures.MySQLOpportunisticFixture


class TestModelsSyncPostgreSQL(
    CinderModelsMigrationsSync,
    test_fixtures.OpportunisticDBTestMixin,
    test_base.BaseTestCase,
):
    FIXTURE = test_fixtures.PostgresqlOpportunisticFixture


class MigrationsWalk(
    test_fixtures.OpportunisticDBTestMixin, test_base.BaseTestCase,
):
    # Migrations can take a long time, particularly on underpowered CI nodes.
    # Give them some breathing room.
    TIMEOUT_SCALING_FACTOR = 4
    BOOL_TYPE = sqlalchemy.types.BOOLEAN

    def setUp(self):
        super().setUp()
        self.engine = enginefacade.writer.get_engine()
        self.patch(api, 'get_engine', lambda: self.engine)
        self.config = migration._find_alembic_conf()
        self.init_version = '921e1a36b076'

    def _migrate_up(self, revision, connection):
        check_method = getattr(self, f'_check_{revision}', None)
        if revision != self.init_version:  # no tests for the initial revision
            self.assertIsNotNone(
                check_method,
                f"API DB Migration {revision} doesn't have a test; add one"
            )

        pre_upgrade = getattr(self, f'_pre_upgrade_{revision}', None)
        if pre_upgrade:
            pre_upgrade(connection)

        alembic_api.upgrade(self.config, revision)

        if check_method:
            check_method(connection)

    def test_single_base_revision(self):
        """Ensure we only have a single base revision.

        There's no good reason for us to have diverging history, so validate
        that only one base revision exists. This will prevent simple errors
        where people forget to specify the base revision. If this fail for your
        change, look for migrations that do not have a 'revises' line in them.
        """
        script = alembic_script.ScriptDirectory.from_config(self.config)
        self.assertEqual(1, len(script.get_bases()))

    def test_single_head_revision(self):
        """Ensure we only have a single head revision.

        There's no good reason for us to have diverging history, so validate
        that only one head revision exists. This will prevent merge conflicts
        adding additional head revision points. If this fail for your change,
        look for migrations with the same 'revises' line in them.
        """
        script = alembic_script.ScriptDirectory.from_config(self.config)
        self.assertEqual(1, len(script.get_heads()))

    def test_walk_versions(self):
        with self.engine.begin() as connection:
            self.config.attributes['connection'] = connection
            script = alembic_script.ScriptDirectory.from_config(self.config)
            revisions = list(script.walk_revisions())
            # Need revisions from older to newer so the walk works as intended
            revisions.reverse()
            for revision_script in revisions:
                self._migrate_up(revision_script.revision, connection)

    def test_db_version_alembic(self):
        migration.db_sync()
        head = alembic_script.ScriptDirectory.from_config(
            self.config,
        ).get_current_head()
        self.assertEqual(head, migration.db_version())

    def _pre_upgrade_c92a3e68beed(self, connection):
        """Test shared_targets is nullable."""
        table = db_utils.get_table(connection, 'volumes')
        self._previous_type = type(table.c.shared_targets.type)

    def _check_c92a3e68beed(self, connection):
        """Test shared_targets is nullable."""
        table = db_utils.get_table(connection, 'volumes')
        self.assertIn('shared_targets', table.c)
        # Type hasn't changed
        self.assertIsInstance(table.c.shared_targets.type, self._previous_type)
        # But it's nullable
        self.assertTrue(table.c.shared_targets.nullable)

    def _check_daa98075b90d(self, connection):
        """Test resources have indexes."""
        for table in ('groups', 'group_snapshots', 'volumes', 'snapshots',
                      'backups'):
            db_utils.index_exists(connection,
                                  table,
                                  f'{table}_deleted_project_id_idx')

        db_utils.index_exists(connection,
                              'volumes', 'volumes_deleted_host_idx')

    def _check_89aa6f9639f9(self, connection):
        # the table only existed on legacy deployments: there's no way to check
        # for its removal without creating it first, which is dumb
        pass


class TestMigrationsWalkSQLite(
    MigrationsWalk,
    test_fixtures.OpportunisticDBTestMixin,
    test_base.BaseTestCase,
):
    pass


class TestMigrationsWalkMySQL(
    MigrationsWalk,
    test_fixtures.OpportunisticDBTestMixin,
    test_base.BaseTestCase,
):
    FIXTURE = test_fixtures.MySQLOpportunisticFixture


class TestMigrationsWalkPostgreSQL(
    MigrationsWalk,
    test_fixtures.OpportunisticDBTestMixin,
    test_base.BaseTestCase,
):
    FIXTURE = test_fixtures.PostgresqlOpportunisticFixture
