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
            # NOTE : 104 modifies size of messages.project_id to 255.
            # This should be safe according to documentation.
            104,
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

    def _check_098(self, engine, data):
        self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                 "messages"))
        ids = self.get_indexed_columns(engine, 'messages')
        self.assertTrue('expires_at' in ids)

    def _check_099(self, engine, data):
        self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                 "volume_attachment"))
        attachment = db_utils.get_table(engine, 'volume_attachment')

        self.assertIsInstance(attachment.c.connection_info.type,
                              self.TEXT_TYPE)

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

    def _pre_upgrade_101(self, engine):
        """Add data to test the SQL migration."""

        types_table = db_utils.get_table(engine, 'volume_types')
        for i in range(1, 5):
            types_table.insert().execute({'id': str(i)})

        specs_table = db_utils.get_table(engine, 'volume_type_extra_specs')
        specs = [
            {'volume_type_id': '1', 'key': 'key', 'value': '<is> False'},
            {'volume_type_id': '2', 'key': 'replication_enabled',
             'value': '<is> False'},
            {'volume_type_id': '3', 'key': 'replication_enabled',
             'value': '<is> True', 'deleted': True},
            {'volume_type_id': '3', 'key': 'key', 'value': '<is> True'},
            {'volume_type_id': '4', 'key': 'replication_enabled',
             'value': '<is> True'},
            {'volume_type_id': '4', 'key': 'key', 'value': '<is> True'},
        ]
        for spec in specs:
            specs_table.insert().execute(spec)

        volumes_table = db_utils.get_table(engine, 'volumes')
        volumes = [
            {'id': '1', 'replication_status': 'disabled',
             'volume_type_id': None},
            {'id': '2', 'replication_status': 'disabled',
             'volume_type_id': ''},
            {'id': '3', 'replication_status': 'disabled',
             'volume_type_id': '1'},
            {'id': '4', 'replication_status': 'disabled',
             'volume_type_id': '2'},
            {'id': '5', 'replication_status': 'disabled',
             'volume_type_id': '2'},
            {'id': '6', 'replication_status': 'disabled',
             'volume_type_id': '3'},
            {'id': '7', 'replication_status': 'error', 'volume_type_id': '4'},
            {'id': '8', 'deleted': True, 'replication_status': 'disabled',
             'volume_type_id': '4'},
            {'id': '9', 'replication_status': 'disabled', 'deleted': None,
             'volume_type_id': '4'},
            {'id': '10', 'replication_status': 'disabled', 'deleted': False,
             'volume_type_id': '4'},
        ]
        for volume in volumes:
            volumes_table.insert().execute(volume)

        # Only the last volume should be changed to enabled
        expected = {v['id']: v['replication_status'] for v in volumes}
        expected['9'] = 'enabled'
        expected['10'] = 'enabled'
        return expected

    def _check_101(self, engine, data):
        # Get existing volumes after the migration
        volumes_table = db_utils.get_table(engine, 'volumes')
        volumes = volumes_table.select().execute()
        # Check that the replication_status is the one we expect according to
        # _pre_upgrade_098
        for volume in volumes:
            self.assertEqual(data[volume.id], volume.replication_status,
                             'id %s' % volume.id)

    def _check_102(self, engine, data):
        """Test adding replication_status to groups table."""
        groups = db_utils.get_table(engine, 'groups')
        self.assertIsInstance(groups.c.replication_status.type,
                              self.VARCHAR_TYPE)

    def _check_103(self, engine, data):
        self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                 "messages"))
        attachment = db_utils.get_table(engine, 'messages')

        self.assertIsInstance(attachment.c.detail_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(attachment.c.action_id.type,
                              self.VARCHAR_TYPE)

    def _check_104(self, engine, data):
        messages = db_utils.get_table(engine, 'messages')
        self.assertEqual(255, messages.c.project_id.type.length)

    def _check_105(self, engine, data):
        self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                 "backup_metadata"))
        backup_metadata = db_utils.get_table(engine, 'backup_metadata')

        self.assertIsInstance(backup_metadata.c.created_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(backup_metadata.c.updated_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(backup_metadata.c.deleted_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(backup_metadata.c.deleted.type,
                              self.BOOL_TYPE)
        self.assertIsInstance(backup_metadata.c.id.type,
                              self.INTEGER_TYPE)
        self.assertIsInstance(backup_metadata.c.key.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(backup_metadata.c.value.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(backup_metadata.c.backup_id.type,
                              self.VARCHAR_TYPE)
        f_keys = self.get_foreign_key_columns(engine, 'backup_metadata')
        self.assertEqual({'backup_id'}, f_keys)

    def _check_111(self, engine, data):
        self.assertTrue(db_utils.index_exists_on_columns(
            engine, 'quota_usages', ['project_id', 'resource']))

    def _check_112(self, engine, data):
        services = db_utils.get_table(engine, 'services')
        self.assertIsInstance(services.c.uuid.type,
                              self.VARCHAR_TYPE)

    def _check_113(self, engine, data):
        """Test that adding reservations index works correctly."""
        reservations = db_utils.get_table(engine, 'reservations')
        index_columns = []
        for idx in reservations.indexes:
            if idx.name == 'reservations_deleted_uuid_idx':
                index_columns = idx.columns.keys()
                break

        self.assertEqual(sorted(['deleted', 'uuid']),
                         sorted(index_columns))

    def _check_114(self, engine, data):
        volumes = db_utils.get_table(engine, 'volumes')
        self.assertIsInstance(volumes.c.service_uuid.type,
                              self.VARCHAR_TYPE)
        index_columns = []
        for idx in volumes.indexes:
            if idx.name == 'volumes_service_uuid_idx':
                index_columns = idx.columns.keys()
                break
        self.assertEqual(sorted(['deleted', 'service_uuid']),
                         sorted(index_columns))

    def _check_115(self, engine, data):
        volumes = db_utils.get_table(engine, 'volumes')
        self.assertIsInstance(volumes.c.shared_targets.type,
                              self.BOOL_TYPE)

    def _check_116(self, engine, data):
        volume_attachment = db_utils.get_table(engine, 'volume_attachment')
        self.assertIn('connector', volume_attachment.c)

    def _check_123(self, engine, data):
        volume_transfer = db_utils.get_table(engine, 'transfers')
        self.assertIn('no_snapshots', volume_transfer.c)

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
