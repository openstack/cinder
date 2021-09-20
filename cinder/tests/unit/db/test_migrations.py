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

import os

from alembic import command as alembic_api
from alembic import script as alembic_script
import fixtures
from migrate.versioning import api as migrate_api
from migrate.versioning import repository
from oslo_db.sqlalchemy import enginefacade
from oslo_db.sqlalchemy import test_fixtures
from oslo_db.sqlalchemy import test_migrations
from oslo_db.sqlalchemy import utils as db_utils
from oslotest import base as test_base
import sqlalchemy
from sqlalchemy.engine import reflection

import cinder.db.legacy_migrations
from cinder.db import migration
from cinder.tests.unit import utils as test_utils
from cinder.volume import volume_types


class MigrationsWalk(
    test_fixtures.OpportunisticDBTestMixin, test_base.BaseTestCase,
):
    def setUp(self):
        super().setUp()
        self.engine = enginefacade.writer.get_engine()
        self.config = migration._find_alembic_conf()
        self.init_version = migration.ALEMBIC_INIT_VERSION

    def _migrate_up(self, revision):
        if revision == self.init_version:  # no tests for the initial revision
            return

        self.assertIsNotNone(
            getattr(self, '_check_%s' % revision, None),
            (
                'API DB Migration %s does not have a test; you must add one'
            ) % revision,
        )
        alembic_api.upgrade(self.config, revision)

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
            for revision_script in script.walk_revisions():
                revision = revision_script.revision
                self._migrate_up(revision)

    def test_db_version_alembic(self):
        migration.db_sync()
        head = alembic_script.ScriptDirectory.from_config(
            self.config,
        ).get_current_head()
        self.assertEqual(head, migration.db_version())


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


class LegacyMigrationsWalk(test_migrations.WalkVersionsMixin):
    """Test sqlalchemy-migrate migrations."""

    BOOL_TYPE = sqlalchemy.types.BOOLEAN
    TIME_TYPE = sqlalchemy.types.DATETIME
    INTEGER_TYPE = sqlalchemy.types.INTEGER
    VARCHAR_TYPE = sqlalchemy.types.VARCHAR
    TEXT_TYPE = sqlalchemy.types.Text

    def setUp(self):
        super().setUp()
        self.engine = enginefacade.writer.get_engine()

    @property
    def INIT_VERSION(self):
        return migration.MIGRATE_INIT_VERSION

    @property
    def REPOSITORY(self):
        migrate_file = cinder.db.legacy_migrations.__file__
        return repository.Repository(
            os.path.abspath(os.path.dirname(migrate_file)))

    @property
    def migration_api(self):
        return migrate_api

    @property
    def migrate_engine(self):
        return self.engine

    def get_table_ref(self, engine, name, metadata):
        metadata.bind = engine
        return sqlalchemy.Table(name, metadata, autoload=True)

    class BannedDBSchemaOperations(fixtures.Fixture):
        """Ban some operations for migrations"""
        def __init__(self, banned_resources=None):
            super().__init__()
            self._banned_resources = banned_resources or []

        @staticmethod
        def _explode(resource, op):
            print('%s.%s()' % (resource, op))  # noqa
            raise Exception(
                'Operation %s.%s() is not allowed in a database migration' % (
                    resource, op))

        def setUp(self):
            super().setUp()
            for thing in self._banned_resources:
                self.useFixture(fixtures.MonkeyPatch(
                    'sqlalchemy.%s.drop' % thing,
                    lambda *a, **k: self._explode(thing, 'drop')))
                self.useFixture(fixtures.MonkeyPatch(
                    'sqlalchemy.%s.alter' % thing,
                    lambda *a, **k: self._explode(thing, 'alter')))

    def migrate_up(self, version, with_data=False):
        # NOTE(dulek): This is a list of migrations where we allow dropping
        # things. The rules for adding things here are very very specific.
        # Insight on how to drop things from the DB in a backward-compatible
        # manner is provided in Cinder's developer documentation.
        # Reviewers: DO NOT ALLOW THINGS TO BE ADDED HERE WITHOUT CARE
        exceptions = [
            # NOTE(brinzhang): 135 changes size of quota_usage.resource
            # to 300. This should be safe for the 'quota_usage' db table,
            # because of the 255 is the length limit of volume_type_name,
            # it should be add the additional prefix before volume_type_name,
            # which we of course allow *this* size to 300.
            135,
            # 136 modifies the the tables having volume_type_id field to set
            # as non nullable
            136,
        ]

        if version not in exceptions:
            banned = ['Table', 'Column']
        else:
            banned = None

        with LegacyMigrationsWalk.BannedDBSchemaOperations(banned):
            super().migrate_up(version, with_data)

    def __check_cinderbase_fields(self, columns):
        """Check fields inherited from CinderBase ORM class."""
        self.assertIsInstance(columns.created_at.type, self.TIME_TYPE)
        self.assertIsInstance(columns.updated_at.type, self.TIME_TYPE)
        self.assertIsInstance(columns.deleted_at.type, self.TIME_TYPE)
        self.assertIsInstance(columns.deleted.type, self.BOOL_TYPE)

    def get_table_names(self, engine):
        inspector = reflection.Inspector.from_engine(engine)
        return inspector.get_table_names()

    def get_foreign_key_columns(self, engine, table_name):
        foreign_keys = set()
        table = db_utils.get_table(engine, table_name)
        inspector = reflection.Inspector.from_engine(engine)
        for column_dict in inspector.get_columns(table_name):
            column_name = column_dict['name']
            column = getattr(table.c, column_name)
            if column.foreign_keys:
                foreign_keys.add(column_name)
        return foreign_keys

    def get_indexed_columns(self, engine, table_name):
        indexed_columns = set()
        for index in db_utils.get_indexes(engine, table_name):
            for column_name in index['column_names']:
                indexed_columns.add(column_name)
        return indexed_columns

    def assert_each_foreign_key_is_part_of_an_index(self):
        engine = self.migrate_engine

        non_indexed_foreign_keys = set()

        for table_name in self.get_table_names(engine):
            indexed_columns = self.get_indexed_columns(engine, table_name)
            foreign_key_columns = self.get_foreign_key_columns(
                engine, table_name
            )
            for column_name in foreign_key_columns - indexed_columns:
                non_indexed_foreign_keys.add(table_name + '.' + column_name)

        self.assertSetEqual(set(), non_indexed_foreign_keys)

    def _check_127(self, engine, data):
        quota_usage_resource = db_utils.get_table(engine, 'quota_usages')
        self.assertIn('resource', quota_usage_resource.c)
        self.assertIsInstance(quota_usage_resource.c.resource.type,
                              self.VARCHAR_TYPE)
        self.assertEqual(300, quota_usage_resource.c.resource.type.length)

    def _check_128(self, engine, data):
        volume_transfer = db_utils.get_table(engine, 'transfers')
        self.assertIn('source_project_id', volume_transfer.c)
        self.assertIn('destination_project_id', volume_transfer.c)
        self.assertIn('accepted', volume_transfer.c)

    def _check_132(self, engine, data):
        """Test create default volume type."""
        vol_types = db_utils.get_table(engine, 'volume_types')
        vtype = (vol_types.select(vol_types.c.name ==
                                  volume_types.DEFAULT_VOLUME_TYPE)
                 .execute().first())
        self.assertIsNotNone(vtype)

    def _check_136(self, engine, data):
        """Test alter volume_type_id columns."""
        vol_table = db_utils.get_table(engine, 'volumes')
        snap_table = db_utils.get_table(engine, 'snapshots')
        encrypt_table = db_utils.get_table(engine, 'encryption')
        self.assertFalse(vol_table.c.volume_type_id.nullable)
        self.assertFalse(snap_table.c.volume_type_id.nullable)
        self.assertFalse(encrypt_table.c.volume_type_id.nullable)

    def _check_145(self, engine, data):
        """Test add use_quota columns."""
        for name in ('volumes', 'snapshots'):
            resources = db_utils.get_table(engine, name)
            self.assertIn('use_quota', resources.c)
            # TODO: (Y release) Alter in new migration & change to assertFalse
            self.assertTrue(resources.c.use_quota.nullable)

    # NOTE: this test becomes slower with each addition of new DB migration.
    # 'pymysql' works much slower on slow nodes than 'psycopg2'. And such
    # timeout mostly required for testing of 'mysql' backend.
    @test_utils.set_timeout(300)
    def test_walk_versions(self):
        self.walk_versions(False, False)
        self.assert_each_foreign_key_is_part_of_an_index()


class TestLegacyMigrationsWalkSQLite(
    test_fixtures.OpportunisticDBTestMixin,
    LegacyMigrationsWalk,
    test_base.BaseTestCase,
):

    def assert_each_foreign_key_is_part_of_an_index(self):
        # Skip the test for SQLite because SQLite does not list
        # UniqueConstraints as indexes, which makes this test fail.
        # Given that SQLite is only for testing purposes, it is safe to skip
        pass


class TestLegacyMigrationsWalkMySQL(
    test_fixtures.OpportunisticDBTestMixin,
    LegacyMigrationsWalk,
    test_base.BaseTestCase,
):

    FIXTURE = test_fixtures.MySQLOpportunisticFixture
    BOOL_TYPE = sqlalchemy.dialects.mysql.TINYINT

    @test_utils.set_timeout(300)
    def test_mysql_innodb(self):
        """Test that table creation on mysql only builds InnoDB tables."""
        # add this to the global lists to make reset work with it, it's removed
        # automatically in tearDown so no need to clean it up here.
        # sanity check
        repo = migration._find_migrate_repo()
        migrate_api.version_control(
            self.migrate_engine, repo, migration.MIGRATE_INIT_VERSION)
        migrate_api.upgrade(self.migrate_engine, repo)

        total = self.migrate_engine.execute(
            "SELECT count(*) "
            "from information_schema.TABLES "
            "where TABLE_SCHEMA='{0}'".format(
                self.migrate_engine.url.database))
        self.assertGreater(total.scalar(), 0,
                           msg="No tables found. Wrong schema?")

        noninnodb = self.migrate_engine.execute(
            "SELECT count(*) "
            "from information_schema.TABLES "
            "where TABLE_SCHEMA='openstack_citest' "
            "and ENGINE!='InnoDB' "
            "and TABLE_NAME!='migrate_version'")
        count = noninnodb.scalar()
        self.assertEqual(count, 0, "%d non InnoDB tables created" % count)

    def _check_127(self, engine, data):
        quota_usage_resource = db_utils.get_table(engine, 'quota_usages')
        self.assertIn('resource', quota_usage_resource.c)
        self.assertIsInstance(quota_usage_resource.c.resource.type,
                              self.VARCHAR_TYPE)
        # Depending on the MariaDB version, and the page size, we may not have
        # been able to change quota_usage_resource to 300 chars, it could still
        # be 255.
        self.assertIn(quota_usage_resource.c.resource.type.length, (255, 300))


class TestLegacyMigrationsWalkPostgreSQL(
    test_fixtures.OpportunisticDBTestMixin,
    LegacyMigrationsWalk,
    test_base.BaseTestCase,
):

    FIXTURE = test_fixtures.PostgresqlOpportunisticFixture
    TIME_TYPE = sqlalchemy.types.TIMESTAMP
