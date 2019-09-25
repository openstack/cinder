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
Tests for database migrations. This test case reads the configuration
file test_migrations.conf for database connection settings
to use in the tests. For each connection found in the config file,
the test case runs a series of test cases to ensure that migrations work
properly both upgrading and downgrading, and that no data loss occurs
if possible.
"""

import os

import fixtures
from migrate.versioning import api as migration_api
from migrate.versioning import repository
from oslo_db.sqlalchemy import enginefacade
from oslo_db.sqlalchemy import test_fixtures
from oslo_db.sqlalchemy import test_migrations
from oslo_db.sqlalchemy import utils as db_utils
from oslotest import base as test_base
import sqlalchemy
from sqlalchemy.engine import reflection

from cinder.db import migration
import cinder.db.sqlalchemy.migrate_repo
from cinder.tests.unit import utils as test_utils
from cinder.volume import volume_types


class MigrationsMixin(test_migrations.WalkVersionsMixin):
    """Test sqlalchemy-migrate migrations."""

    BOOL_TYPE = sqlalchemy.types.BOOLEAN
    TIME_TYPE = sqlalchemy.types.DATETIME
    INTEGER_TYPE = sqlalchemy.types.INTEGER
    VARCHAR_TYPE = sqlalchemy.types.VARCHAR
    TEXT_TYPE = sqlalchemy.types.Text

    @property
    def INIT_VERSION(self):
        return migration.INIT_VERSION

    @property
    def REPOSITORY(self):
        migrate_file = cinder.db.sqlalchemy.migrate_repo.__file__
        return repository.Repository(
            os.path.abspath(os.path.dirname(migrate_file)))

    @property
    def migration_api(self):
        return migration_api

    def setUp(self):
        super(MigrationsMixin, self).setUp()

        # (zzzeek) This mixin states that it uses the
        # "self.engine" attribute in the migrate_engine() method.
        # So the mixin must set that up for itself, oslo_db no longer
        # makes these assumptions for you.
        self.engine = enginefacade.writer.get_engine()

    @property
    def migrate_engine(self):
        return self.engine

    def get_table_ref(self, engine, name, metadata):
        metadata.bind = engine
        return sqlalchemy.Table(name, metadata, autoload=True)

    class BannedDBSchemaOperations(fixtures.Fixture):
        """Ban some operations for migrations"""
        def __init__(self, banned_resources=None):
            super(MigrationsMixin.BannedDBSchemaOperations, self).__init__()
            self._banned_resources = banned_resources or []

        @staticmethod
        def _explode(resource, op):
            print('%s.%s()' % (resource, op))  # noqa
            raise Exception(
                'Operation %s.%s() is not allowed in a database migration' % (
                    resource, op))

        def setUp(self):
            super(MigrationsMixin.BannedDBSchemaOperations, self).setUp()
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
            # NOTE(brinzhang): 127 changes size of quota_usage.resource
            # to 300. This should be safe for the 'quota_usage' db table,
            # because of the 255 is the length limit of volume_type_name,
            # it should be add the additional prefix before volume_type_name,
            # which we of course allow *this* size to 300.
            127,
        ]

        if version not in exceptions:
            banned = ['Table', 'Column']
        else:
            banned = None
        with MigrationsMixin.BannedDBSchemaOperations(banned):
            super(MigrationsMixin, self).migrate_up(version, with_data)

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

    # NOTE: this test becomes slower with each addition of new DB migration.
    # 'pymysql' works much slower on slow nodes than 'psycopg2'. And such
    # timeout mostly required for testing of 'mysql' backend.
    @test_utils.set_timeout(300)
    def test_walk_versions(self):
        self.walk_versions(False, False)
        self.assert_each_foreign_key_is_part_of_an_index()


class TestSqliteMigrations(test_fixtures.OpportunisticDBTestMixin,
                           MigrationsMixin,
                           test_base.BaseTestCase):

    def assert_each_foreign_key_is_part_of_an_index(self):
        # Skip the test for SQLite because SQLite does not list
        # UniqueConstraints as indexes, which makes this test fail.
        # Given that SQLite is only for testing purposes, it is safe to skip
        pass


class TestMysqlMigrations(test_fixtures.OpportunisticDBTestMixin,
                          MigrationsMixin,
                          test_base.BaseTestCase):

    FIXTURE = test_fixtures.MySQLOpportunisticFixture
    BOOL_TYPE = sqlalchemy.dialects.mysql.TINYINT

    @test_utils.set_timeout(300)
    def test_mysql_innodb(self):
        """Test that table creation on mysql only builds InnoDB tables."""
        # add this to the global lists to make reset work with it, it's removed
        # automatically in tearDown so no need to clean it up here.
        # sanity check
        migration.db_sync(engine=self.migrate_engine)

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
        self.assertIn(quota_usage_resource.c.resource.type.length,
                      (255, 300))


class TestPostgresqlMigrations(test_fixtures.OpportunisticDBTestMixin,
                               MigrationsMixin,
                               test_base.BaseTestCase):

    FIXTURE = test_fixtures.PostgresqlOpportunisticFixture
    TIME_TYPE = sqlalchemy.types.TIMESTAMP
