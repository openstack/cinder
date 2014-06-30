
# Copyright 2010-2011 OpenStack Foundation
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

"""
Tests for database migrations. This test case reads the configuration
file test_migrations.conf for database connection settings
to use in the tests. For each connection found in the config file,
the test case runs a series of test cases to ensure that migrations work
properly both upgrading and downgrading, and that no data loss occurs
if possible.
"""

import ConfigParser
import os
import subprocess
import uuid

from migrate.versioning import repository
import six.moves.urllib.parse as urlparse
import sqlalchemy
import testtools

import cinder.db.migration as migration
import cinder.db.sqlalchemy.migrate_repo
from cinder.db.sqlalchemy.migration import versioning_api as migration_api
from cinder.openstack.common import log as logging
from cinder import test

LOG = logging.getLogger('cinder.tests.test_migrations')


def _get_connect_string(backend,
                        user="openstack_citest",
                        passwd="openstack_citest",
                        database="openstack_citest"):
    """Return connect string.

    Try to get a connection with a very specific set of values, if we get
    these then we'll run the tests, otherwise they are skipped.
    """
    if backend == "postgres":
        backend = "postgresql+psycopg2"

    return ("%(backend)s://%(user)s:%(passwd)s@localhost/%(database)s" %
            {'backend': backend, 'user': user, 'passwd': passwd,
             'database': database})


def _is_mysql_avail(**kwargs):
    return _is_backend_avail('mysql', **kwargs)


def _is_backend_avail(backend,
                      user="openstack_citest",
                      passwd="openstack_citest",
                      database="openstack_citest"):
    try:
        if backend == "mysql":
            connect_uri = _get_connect_string("mysql", user=user,
                                              passwd=passwd, database=database)
        elif backend == "postgres":
            connect_uri = _get_connect_string("postgres", user=user,
                                              passwd=passwd, database=database)
        engine = sqlalchemy.create_engine(connect_uri)
        connection = engine.connect()
    except Exception:
        # intentionally catch all to handle exceptions even if we don't
        # have any backend code loaded.
        LOG.exception("Backend %s is not available", backend)
        return False
    else:
        connection.close()
        engine.dispose()
        return True


def _have_mysql():
    present = os.environ.get('NOVA_TEST_MYSQL_PRESENT')
    if present is None:
        return _is_backend_avail('mysql')
    return present.lower() in ('', 'true')


def get_table(engine, name):
    """Returns an sqlalchemy table dynamically from db.

    Needed because the models don't work for us in migrations
    as models will be far out of sync with the current data.
    """
    metadata = sqlalchemy.schema.MetaData()
    metadata.bind = engine
    return sqlalchemy.Table(name, metadata, autoload=True)


class TestMigrations(test.TestCase):
    """Test sqlalchemy-migrate migrations."""

    DEFAULT_CONFIG_FILE = os.path.join(os.path.dirname(__file__),
                                       'test_migrations.conf')
    # Test machines can set the CINDER_TEST_MIGRATIONS_CONF variable
    # to override the location of the config file for migration testing
    CONFIG_FILE_PATH = os.environ.get('CINDER_TEST_MIGRATIONS_CONF',
                                      DEFAULT_CONFIG_FILE)
    MIGRATE_FILE = cinder.db.sqlalchemy.migrate_repo.__file__
    REPOSITORY = repository.Repository(
        os.path.abspath(os.path.dirname(MIGRATE_FILE)))

    def setUp(self):
        super(TestMigrations, self).setUp()

        self.snake_walk = False
        self.test_databases = {}

        # Load test databases from the config file. Only do this
        # once. No need to re-run this on each test...
        LOG.debug('config_path is %s' % TestMigrations.CONFIG_FILE_PATH)
        if not self.test_databases:
            if os.path.exists(TestMigrations.CONFIG_FILE_PATH):
                cp = ConfigParser.RawConfigParser()
                try:
                    cp.read(TestMigrations.CONFIG_FILE_PATH)
                    defaults = cp.defaults()
                    for key, value in defaults.items():
                        self.test_databases[key] = value
                    self.snake_walk = cp.getboolean('walk_style', 'snake_walk')
                except ConfigParser.ParsingError as e:
                    self.fail("Failed to read test_migrations.conf config "
                              "file. Got error: %s" % e)
            else:
                self.fail("Failed to find test_migrations.conf config "
                          "file.")

        self.engines = {}
        for key, value in self.test_databases.items():
            self.engines[key] = sqlalchemy.create_engine(value)

        # Set-up a dict of types for those column types that
        # are not uniform for all databases.
        self.bool_type = {}
        self.time_type = {}
        for (key, engine) in self.engines.items():
            self.bool_type[engine.name] = sqlalchemy.types.BOOLEAN
            self.time_type[engine.name] = sqlalchemy.types.DATETIME
            if engine.name == 'mysql':
                self.bool_type[engine.name] = sqlalchemy.dialects.mysql.TINYINT
            if engine.name == 'postgresql':
                self.time_type[engine.name] = sqlalchemy.types.TIMESTAMP

        # We start each test case with a completely blank slate.
        self._reset_databases()

        # We destroy the test data store between each test case,
        # and recreate it, which ensures that we have no side-effects
        # from the tests
        self.addCleanup(self._reset_databases)

    def _reset_databases(self):
        def execute_cmd(cmd=None):
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, shell=True)
            output = proc.communicate()[0]
            LOG.debug(output)
            self.assertEqual(0, proc.returncode)

        for key, engine in self.engines.items():
            conn_string = self.test_databases[key]
            conn_pieces = urlparse.urlparse(conn_string)
            engine.dispose()
            if conn_string.startswith('sqlite'):
                # We can just delete the SQLite database, which is
                # the easiest and cleanest solution
                db_path = conn_pieces.path.strip('/')
                if os.path.exists(db_path):
                    os.unlink(db_path)
                # No need to recreate the SQLite DB. SQLite will
                # create it for us if it's not there...
            elif conn_string.startswith('mysql'):
                # We can execute the MySQL client to destroy and re-create
                # the MYSQL database, which is easier and less error-prone
                # than using SQLAlchemy to do this via MetaData...trust me.
                database = conn_pieces.path.strip('/')
                loc_pieces = conn_pieces.netloc.split('@')
                host = loc_pieces[1]
                auth_pieces = loc_pieces[0].split(':')
                user = auth_pieces[0]
                password = ""
                if len(auth_pieces) > 1:
                    if auth_pieces[1].strip():
                        password = "-p\"%s\"" % auth_pieces[1]
                sql = ("drop database if exists %(database)s; create database "
                       "%(database)s;") % {'database': database}
                cmd = ("mysql -u \"%(user)s\" %(password)s -h %(host)s "
                       "-e \"%(sql)s\"") % {'user': user, 'password': password,
                                            'host': host, 'sql': sql}
                execute_cmd(cmd)
            elif conn_string.startswith('postgresql'):
                database = conn_pieces.path.strip('/')
                loc_pieces = conn_pieces.netloc.split('@')
                host = loc_pieces[1]

                auth_pieces = loc_pieces[0].split(':')
                user = auth_pieces[0]
                password = ""
                if len(auth_pieces) > 1:
                    password = auth_pieces[1].strip()
                # note(krtaylor): File creation problems with tests in
                # venv using .pgpass authentication, changed to
                # PGPASSWORD environment variable which is no longer
                # planned to be deprecated
                os.environ['PGPASSWORD'] = password
                os.environ['PGUSER'] = user
                # note(boris-42): We must create and drop database, we can't
                # drop database which we have connected to, so for such
                # operations there is a special database template1.
                sqlcmd = ("psql -w -U %(user)s -h %(host)s -c"
                          " '%(sql)s' -d template1")
                sql = ("drop database if exists %(database)s;") % {'database':
                                                                   database}
                droptable = sqlcmd % {'user': user, 'host': host, 'sql': sql}
                execute_cmd(droptable)
                sql = ("create database %(database)s;") % {'database':
                                                           database}
                createtable = sqlcmd % {'user': user, 'host': host, 'sql': sql}
                execute_cmd(createtable)
                os.unsetenv('PGPASSWORD')
                os.unsetenv('PGUSER')

    def test_walk_versions(self):
        """Test walk versions.

        Walks all version scripts for each tested database, ensuring
        that there are no errors in the version scripts for each engine
        """
        for key, engine in self.engines.items():
            self._walk_versions(engine, self.snake_walk)

    def test_mysql_connect_fail(self):
        """Test for mysql connection failure.

        Test that we can trigger a mysql connection failure and we fail
        gracefully to ensure we don't break people without mysql
        """
        if _is_mysql_avail(user="openstack_cifail"):
            self.fail("Shouldn't have connected")

    @testtools.skipUnless(_have_mysql(), "mysql not available")
    def test_mysql_innodb(self):
        """Test that table creation on mysql only builds InnoDB tables."""
        # add this to the global lists to make reset work with it, it's removed
        # automatically in tearDown so no need to clean it up here.
        connect_string = _get_connect_string('mysql')
        engine = sqlalchemy.create_engine(connect_string)
        self.engines["mysqlcitest"] = engine
        self.test_databases["mysqlcitest"] = connect_string

        # build a fully populated mysql database with all the tables
        self._reset_databases()
        self._walk_versions(engine, False, False)

        uri = _get_connect_string('mysql', database="information_schema")
        connection = sqlalchemy.create_engine(uri).connect()

        # sanity check
        total = connection.execute("SELECT count(*) "
                                   "from information_schema.TABLES "
                                   "where TABLE_SCHEMA='openstack_citest'")
        self.assertGreater(total.scalar(), 0,
                           msg="No tables found. Wrong schema?")

        noninnodb = connection.execute("SELECT count(*) "
                                       "from information_schema.TABLES "
                                       "where TABLE_SCHEMA='openstack_citest' "
                                       "and ENGINE!='InnoDB' "
                                       "and TABLE_NAME!='migrate_version'")
        count = noninnodb.scalar()
        self.assertEqual(count, 0, "%d non InnoDB tables created" % count)

    def test_postgresql_connect_fail(self):
        """Test connection failure on PostgrSQL.

        Test that we can trigger a postgres connection failure and we fail
        gracefully to ensure we don't break people without postgres.
        """
        if _is_backend_avail('postgres', user="openstack_cifail"):
            self.fail("Shouldn't have connected")

    @testtools.skipUnless(_is_backend_avail('postgres'),
                          "postgresql not available")
    def test_postgresql_opportunistically(self):
        # add this to the global lists to make reset work with it, it's removed
        # automatically in tearDown so no need to clean it up here.
        connect_string = _get_connect_string("postgres")
        engine = sqlalchemy.create_engine(connect_string)
        self.engines["postgresqlcitest"] = engine
        self.test_databases["postgresqlcitest"] = connect_string

        # build a fully populated postgresql database with all the tables
        self._reset_databases()
        self._walk_versions(engine, False, False)

    def _walk_versions(self, engine=None, snake_walk=False, downgrade=True):
        # Determine latest version script from the repo, then
        # upgrade from 1 through to the latest, with no data
        # in the databases. This just checks that the schema itself
        # upgrades successfully.

        # Place the database under version control
        migration_api.version_control(engine,
                                      TestMigrations.REPOSITORY,
                                      migration.db_initial_version())
        self.assertEqual(migration.db_initial_version(),
                         migration_api.db_version(engine,
                                                  TestMigrations.REPOSITORY))

        migration_api.upgrade(engine, TestMigrations.REPOSITORY,
                              migration.db_initial_version() + 1)

        LOG.debug('latest version is %s' % TestMigrations.REPOSITORY.latest)

        for version in xrange(migration.db_initial_version() + 2,
                              TestMigrations.REPOSITORY.latest + 1):
            # upgrade -> downgrade -> upgrade
            self._migrate_up(engine, version, with_data=True)
            if snake_walk:
                self._migrate_down(engine, version - 1)
                self._migrate_up(engine, version)

        if downgrade:
            # Now walk it back down to 0 from the latest, testing
            # the downgrade paths.
            for version in reversed(
                xrange(migration.db_initial_version() + 1,
                       TestMigrations.REPOSITORY.latest)):
                # downgrade -> upgrade -> downgrade
                self._migrate_down(engine, version)
                if snake_walk:
                    self._migrate_up(engine, version + 1)
                    self._migrate_down(engine, version)

    def _migrate_down(self, engine, version):
        migration_api.downgrade(engine,
                                TestMigrations.REPOSITORY,
                                version)
        self.assertEqual(version,
                         migration_api.db_version(engine,
                                                  TestMigrations.REPOSITORY))

    def _migrate_up(self, engine, version, with_data=False):
        """Migrate up to a new version of the db.

        We allow for data insertion and post checks at every
        migration version with special _prerun_### and
        _check_### functions in the main test.
        """
        # NOTE(sdague): try block is here because it's impossible to debug
        # where a failed data migration happens otherwise
        try:
            if with_data:
                data = None
                prerun = getattr(self, "_prerun_%3.3d" % version, None)
                if prerun:
                    data = prerun(engine)

            migration_api.upgrade(engine,
                                  TestMigrations.REPOSITORY,
                                  version)
            self.assertEqual(
                version,
                migration_api.db_version(engine,
                                         TestMigrations.REPOSITORY))

            if with_data:
                check = getattr(self, "_check_%3.3d" % version, None)
                if check:
                    check(engine, data)
        except Exception:
            LOG.error("Failed to migrate to version %s on engine %s" %
                      (version, engine))
            raise

    # migration 004 - change volume types to UUID
    def _prerun_004(self, engine):
        data = {
            'volumes': [{'id': str(uuid.uuid4()), 'host': 'test1',
                         'volume_type_id': 1},
                        {'id': str(uuid.uuid4()), 'host': 'test2',
                         'volume_type_id': 1},
                        {'id': str(uuid.uuid4()), 'host': 'test3',
                         'volume_type_id': 3},
                        ],
            'volume_types': [{'name': 'vtype1'},
                             {'name': 'vtype2'},
                             {'name': 'vtype3'},
                             ],
            'volume_type_extra_specs': [{'volume_type_id': 1,
                                         'key': 'v1',
                                         'value': 'hotep',
                                         },
                                        {'volume_type_id': 1,
                                         'key': 'v2',
                                         'value': 'bending rodrigez',
                                         },
                                        {'volume_type_id': 2,
                                         'key': 'v3',
                                         'value': 'bending rodrigez',
                                         },
                                        ]}

        volume_types = get_table(engine, 'volume_types')
        for vtype in data['volume_types']:
            r = volume_types.insert().values(vtype).execute()
            vtype['id'] = r.inserted_primary_key[0]

        volume_type_es = get_table(engine, 'volume_type_extra_specs')
        for vtes in data['volume_type_extra_specs']:
            r = volume_type_es.insert().values(vtes).execute()
            vtes['id'] = r.inserted_primary_key[0]

        volumes = get_table(engine, 'volumes')
        for vol in data['volumes']:
            r = volumes.insert().values(vol).execute()
            vol['id'] = r.inserted_primary_key[0]

        return data

    def _check_004(self, engine, data):
        volumes = get_table(engine, 'volumes')
        v1 = volumes.select(volumes.c.id ==
                            data['volumes'][0]['id']
                            ).execute().first()
        v2 = volumes.select(volumes.c.id ==
                            data['volumes'][1]['id']
                            ).execute().first()
        v3 = volumes.select(volumes.c.id ==
                            data['volumes'][2]['id']
                            ).execute().first()

        volume_types = get_table(engine, 'volume_types')
        vt1 = volume_types.select(volume_types.c.name ==
                                  data['volume_types'][0]['name']
                                  ).execute().first()
        vt2 = volume_types.select(volume_types.c.name ==
                                  data['volume_types'][1]['name']
                                  ).execute().first()
        vt3 = volume_types.select(volume_types.c.name ==
                                  data['volume_types'][2]['name']
                                  ).execute().first()

        vtes = get_table(engine, 'volume_type_extra_specs')
        vtes1 = vtes.select(vtes.c.key ==
                            data['volume_type_extra_specs'][0]['key']
                            ).execute().first()
        vtes2 = vtes.select(vtes.c.key ==
                            data['volume_type_extra_specs'][1]['key']
                            ).execute().first()
        vtes3 = vtes.select(vtes.c.key ==
                            data['volume_type_extra_specs'][2]['key']
                            ).execute().first()

        self.assertEqual(v1['volume_type_id'], vt1['id'])
        self.assertEqual(v2['volume_type_id'], vt1['id'])
        self.assertEqual(v3['volume_type_id'], vt3['id'])

        self.assertEqual(vtes1['volume_type_id'], vt1['id'])
        self.assertEqual(vtes2['volume_type_id'], vt1['id'])
        self.assertEqual(vtes3['volume_type_id'], vt2['id'])

    def test_migration_005(self):
        """Test that adding source_volid column works correctly."""
        for (key, engine) in self.engines.items():
            migration_api.version_control(engine,
                                          TestMigrations.REPOSITORY,
                                          migration.db_initial_version())
            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 4)
            metadata = sqlalchemy.schema.MetaData()
            metadata.bind = engine

            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 5)
            volumes = sqlalchemy.Table('volumes',
                                       metadata,
                                       autoload=True)
            self.assertIsInstance(volumes.c.source_volid.type,
                                  sqlalchemy.types.VARCHAR)

    def _metadatas(self, upgrade_to, downgrade_to=None):
        for (key, engine) in self.engines.items():
            migration_api.version_control(engine,
                                          TestMigrations.REPOSITORY,
                                          migration.db_initial_version())
            migration_api.upgrade(engine,
                                  TestMigrations.REPOSITORY,
                                  upgrade_to)

            if downgrade_to is not None:
                migration_api.downgrade(
                    engine, TestMigrations.REPOSITORY, downgrade_to)

            metadata = sqlalchemy.schema.MetaData()
            metadata.bind = engine
            yield metadata

    def metadatas_upgraded_to(self, revision):
        return self._metadatas(revision)

    def metadatas_downgraded_from(self, revision):
        return self._metadatas(revision, revision - 1)

    def test_upgrade_006_adds_provider_location(self):
        for metadata in self.metadatas_upgraded_to(6):
            snapshots = sqlalchemy.Table('snapshots', metadata, autoload=True)
            self.assertIsInstance(snapshots.c.provider_location.type,
                                  sqlalchemy.types.VARCHAR)

    def test_downgrade_006_removes_provider_location(self):
        for metadata in self.metadatas_downgraded_from(6):
            snapshots = sqlalchemy.Table('snapshots', metadata, autoload=True)

            self.assertNotIn('provider_location', snapshots.c)

    def test_upgrade_007_adds_fk(self):
        for metadata in self.metadatas_upgraded_to(7):
            snapshots = sqlalchemy.Table('snapshots', metadata, autoload=True)
            volumes = sqlalchemy.Table('volumes', metadata, autoload=True)

            fkey, = snapshots.c.volume_id.foreign_keys

            self.assertEqual(volumes.c.id, fkey.column)

    def test_downgrade_007_removes_fk(self):
        for metadata in self.metadatas_downgraded_from(7):
            snapshots = sqlalchemy.Table('snapshots', metadata, autoload=True)

            self.assertEqual(0, len(snapshots.c.volume_id.foreign_keys))

    def test_migration_008(self):
        """Test that adding and removing the backups table works correctly."""
        for (key, engine) in self.engines.items():
            migration_api.version_control(engine,
                                          TestMigrations.REPOSITORY,
                                          migration.db_initial_version())
            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 7)
            metadata = sqlalchemy.schema.MetaData()
            metadata.bind = engine

            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 8)

            self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                     "backups"))
            backups = sqlalchemy.Table('backups',
                                       metadata,
                                       autoload=True)

            self.assertIsInstance(backups.c.created_at.type,
                                  self.time_type[engine.name])
            self.assertIsInstance(backups.c.updated_at.type,
                                  self.time_type[engine.name])
            self.assertIsInstance(backups.c.deleted_at.type,
                                  self.time_type[engine.name])
            self.assertIsInstance(backups.c.deleted.type,
                                  self.bool_type[engine.name])
            self.assertIsInstance(backups.c.id.type,
                                  sqlalchemy.types.VARCHAR)
            self.assertIsInstance(backups.c.volume_id.type,
                                  sqlalchemy.types.VARCHAR)
            self.assertIsInstance(backups.c.user_id.type,
                                  sqlalchemy.types.VARCHAR)
            self.assertIsInstance(backups.c.project_id.type,
                                  sqlalchemy.types.VARCHAR)
            self.assertIsInstance(backups.c.host.type,
                                  sqlalchemy.types.VARCHAR)
            self.assertIsInstance(backups.c.availability_zone.type,
                                  sqlalchemy.types.VARCHAR)
            self.assertIsInstance(backups.c.display_name.type,
                                  sqlalchemy.types.VARCHAR)
            self.assertIsInstance(backups.c.display_description.type,
                                  sqlalchemy.types.VARCHAR)
            self.assertIsInstance(backups.c.container.type,
                                  sqlalchemy.types.VARCHAR)
            self.assertIsInstance(backups.c.status.type,
                                  sqlalchemy.types.VARCHAR)
            self.assertIsInstance(backups.c.fail_reason.type,
                                  sqlalchemy.types.VARCHAR)
            self.assertIsInstance(backups.c.service_metadata.type,
                                  sqlalchemy.types.VARCHAR)
            self.assertIsInstance(backups.c.service.type,
                                  sqlalchemy.types.VARCHAR)
            self.assertIsInstance(backups.c.size.type,
                                  sqlalchemy.types.INTEGER)
            self.assertIsInstance(backups.c.object_count.type,
                                  sqlalchemy.types.INTEGER)

            migration_api.downgrade(engine, TestMigrations.REPOSITORY, 7)

            self.assertFalse(engine.dialect.has_table(engine.connect(),
                                                      "backups"))

    def test_migration_009(self):
        """Test adding snapshot_metadata table works correctly."""
        for (key, engine) in self.engines.items():
            migration_api.version_control(engine,
                                          TestMigrations.REPOSITORY,
                                          migration.db_initial_version())
            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 8)
            metadata = sqlalchemy.schema.MetaData()
            metadata.bind = engine

            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 9)

            self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                     "snapshot_metadata"))
            snapshot_metadata = sqlalchemy.Table('snapshot_metadata',
                                                 metadata,
                                                 autoload=True)

            self.assertIsInstance(snapshot_metadata.c.created_at.type,
                                  self.time_type[engine.name])
            self.assertIsInstance(snapshot_metadata.c.updated_at.type,
                                  self.time_type[engine.name])
            self.assertIsInstance(snapshot_metadata.c.deleted_at.type,
                                  self.time_type[engine.name])
            self.assertIsInstance(snapshot_metadata.c.deleted.type,
                                  self.bool_type[engine.name])
            self.assertIsInstance(snapshot_metadata.c.deleted.type,
                                  self.bool_type[engine.name])
            self.assertIsInstance(snapshot_metadata.c.id.type,
                                  sqlalchemy.types.INTEGER)
            self.assertIsInstance(snapshot_metadata.c.snapshot_id.type,
                                  sqlalchemy.types.VARCHAR)
            self.assertIsInstance(snapshot_metadata.c.key.type,
                                  sqlalchemy.types.VARCHAR)
            self.assertIsInstance(snapshot_metadata.c.value.type,
                                  sqlalchemy.types.VARCHAR)

            migration_api.downgrade(engine, TestMigrations.REPOSITORY, 8)

            self.assertFalse(engine.dialect.has_table(engine.connect(),
                                                      "snapshot_metadata"))

    def test_migration_010(self):
        """Test adding transfers table works correctly."""
        for (key, engine) in self.engines.items():
            migration_api.version_control(engine,
                                          TestMigrations.REPOSITORY,
                                          migration.db_initial_version())
            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 9)
            metadata = sqlalchemy.schema.MetaData()
            metadata.bind = engine

            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 10)
            self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                     "transfers"))
            transfers = sqlalchemy.Table('transfers',
                                         metadata,
                                         autoload=True)

            self.assertIsInstance(transfers.c.created_at.type,
                                  self.time_type[engine.name])
            self.assertIsInstance(transfers.c.updated_at.type,
                                  self.time_type[engine.name])
            self.assertIsInstance(transfers.c.deleted_at.type,
                                  self.time_type[engine.name])
            self.assertIsInstance(transfers.c.deleted.type,
                                  self.bool_type[engine.name])
            self.assertIsInstance(transfers.c.id.type,
                                  sqlalchemy.types.VARCHAR)
            self.assertIsInstance(transfers.c.volume_id.type,
                                  sqlalchemy.types.VARCHAR)
            self.assertIsInstance(transfers.c.display_name.type,
                                  sqlalchemy.types.VARCHAR)
            self.assertIsInstance(transfers.c.salt.type,
                                  sqlalchemy.types.VARCHAR)
            self.assertIsInstance(transfers.c.crypt_hash.type,
                                  sqlalchemy.types.VARCHAR)
            self.assertIsInstance(transfers.c.expires_at.type,
                                  self.time_type[engine.name])

            migration_api.downgrade(engine, TestMigrations.REPOSITORY, 9)

            self.assertFalse(engine.dialect.has_table(engine.connect(),
                                                      "transfers"))

    def test_migration_011(self):
        """Test adding transfers table works correctly."""
        for (key, engine) in self.engines.items():
            migration_api.version_control(engine,
                                          TestMigrations.REPOSITORY,
                                          migration.db_initial_version())
            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 10)
            metadata = sqlalchemy.schema.MetaData()
            metadata.bind = engine

            volumes_v10 = sqlalchemy.Table('volumes',
                                           metadata,
                                           autoload=True)

            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 11)
            metadata = sqlalchemy.schema.MetaData()
            metadata.bind = engine

            self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                     "volumes"))
            volumes = sqlalchemy.Table('volumes',
                                       metadata,
                                       autoload=True)

            # Make sure we didn't miss any columns in the upgrade
            for column in volumes_v10.c:
                self.assertTrue(volumes.c.__contains__(column.name))

            self.assertIsInstance(volumes.c.bootable.type,
                                  self.bool_type[engine.name])

            migration_api.downgrade(engine, TestMigrations.REPOSITORY, 10)
            metadata = sqlalchemy.schema.MetaData()
            metadata.bind = engine

            volumes = sqlalchemy.Table('volumes',
                                       metadata,
                                       autoload=True)
            self.assertNotIn('bootable', volumes.c)

            # Make sure we put all the columns back
            for column in volumes_v10.c:
                self.assertTrue(volumes.c.__contains__(column.name))

    def test_migration_012(self):
        """Test that adding attached_host column works correctly."""
        for (key, engine) in self.engines.items():
            migration_api.version_control(engine,
                                          TestMigrations.REPOSITORY,
                                          migration.db_initial_version())
            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 11)
            metadata = sqlalchemy.schema.MetaData()
            metadata.bind = engine

            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 12)
            volumes = sqlalchemy.Table('volumes',
                                       metadata,
                                       autoload=True)
            self.assertIsInstance(volumes.c.attached_host.type,
                                  sqlalchemy.types.VARCHAR)

            migration_api.downgrade(engine, TestMigrations.REPOSITORY, 11)
            metadata = sqlalchemy.schema.MetaData()
            metadata.bind = engine

            volumes = sqlalchemy.Table('volumes',
                                       metadata,
                                       autoload=True)
            self.assertNotIn('attached_host', volumes.c)

    def test_migration_013(self):
        """Test that adding provider_geometry column works correctly."""
        for (key, engine) in self.engines.items():
            migration_api.version_control(engine,
                                          TestMigrations.REPOSITORY,
                                          migration.db_initial_version())
            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 12)
            metadata = sqlalchemy.schema.MetaData()
            metadata.bind = engine

            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 13)
            volumes = sqlalchemy.Table('volumes',
                                       metadata,
                                       autoload=True)
            self.assertIsInstance(volumes.c.provider_geometry.type,
                                  sqlalchemy.types.VARCHAR)

            migration_api.downgrade(engine, TestMigrations.REPOSITORY, 12)
            metadata = sqlalchemy.schema.MetaData()
            metadata.bind = engine

            volumes = sqlalchemy.Table('volumes',
                                       metadata,
                                       autoload=True)
            self.assertNotIn('provider_geometry', volumes.c)

    def test_migration_014(self):
        """Test that adding _name_id column works correctly."""
        for (key, engine) in self.engines.items():
            migration_api.version_control(engine,
                                          TestMigrations.REPOSITORY,
                                          migration.db_initial_version())
            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 13)
            metadata = sqlalchemy.schema.MetaData()
            metadata.bind = engine

            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 14)
            volumes = sqlalchemy.Table('volumes',
                                       metadata,
                                       autoload=True)
            self.assertIsInstance(volumes.c._name_id.type,
                                  sqlalchemy.types.VARCHAR)

            migration_api.downgrade(engine, TestMigrations.REPOSITORY, 13)
            metadata = sqlalchemy.schema.MetaData()
            metadata.bind = engine

            volumes = sqlalchemy.Table('volumes',
                                       metadata,
                                       autoload=True)
            self.assertNotIn('_name_id', volumes.c)

    def test_migration_015(self):
        """Test removing migrations table works correctly."""
        for (key, engine) in self.engines.items():
            migration_api.version_control(engine,
                                          TestMigrations.REPOSITORY,
                                          migration.db_initial_version())
            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 15)

            self.assertFalse(engine.dialect.has_table(engine.connect(),
                                                      "migrations"))

            migration_api.downgrade(engine, TestMigrations.REPOSITORY, 14)

            self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                     "migrations"))

    def test_migration_016(self):
        """Test that dropping xen storage manager tables works correctly."""
        for (key, engine) in self.engines.items():
            migration_api.version_control(engine,
                                          TestMigrations.REPOSITORY,
                                          migration.db_initial_version())
            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 15)
            metadata = sqlalchemy.schema.MetaData()
            metadata.bind = engine

            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 16)
            self.assertFalse(engine.dialect.has_table(engine.connect(),
                                                      'sm_flavors'))
            self.assertFalse(engine.dialect.has_table(engine.connect(),
                                                      'sm_backend_config'))
            self.assertFalse(engine.dialect.has_table(engine.connect(),
                                                      'sm_volume'))

            migration_api.downgrade(engine, TestMigrations.REPOSITORY, 15)
            self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                     'sm_flavors'))
            self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                     'sm_backend_config'))
            self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                     'sm_volume'))

    def test_migration_017(self):
        """Test that added encryption information works correctly."""

        # upgrade schema
        for (key, engine) in self.engines.items():
            migration_api.version_control(engine,
                                          TestMigrations.REPOSITORY,
                                          migration.db_initial_version())
            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 16)
            metadata = sqlalchemy.schema.MetaData()
            metadata.bind = engine

            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 17)

            # encryption key UUID
            volumes = sqlalchemy.Table('volumes', metadata, autoload=True)
            self.assertIn('encryption_key_id', volumes.c)
            self.assertIsInstance(volumes.c.encryption_key_id.type,
                                  sqlalchemy.types.VARCHAR)

            snapshots = sqlalchemy.Table('snapshots', metadata, autoload=True)
            self.assertIn('encryption_key_id', snapshots.c)
            self.assertIsInstance(snapshots.c.encryption_key_id.type,
                                  sqlalchemy.types.VARCHAR)
            self.assertIn('volume_type_id', snapshots.c)
            self.assertIsInstance(snapshots.c.volume_type_id.type,
                                  sqlalchemy.types.VARCHAR)

            # encryption types table
            encryption = sqlalchemy.Table('encryption',
                                          metadata,
                                          autoload=True)
            self.assertIsInstance(encryption.c.volume_type_id.type,
                                  sqlalchemy.types.VARCHAR)
            self.assertIsInstance(encryption.c.cipher.type,
                                  sqlalchemy.types.VARCHAR)
            self.assertIsInstance(encryption.c.key_size.type,
                                  sqlalchemy.types.INTEGER)
            self.assertIsInstance(encryption.c.provider.type,
                                  sqlalchemy.types.VARCHAR)

            # downgrade schema
            migration_api.downgrade(engine, TestMigrations.REPOSITORY, 16)
            metadata = sqlalchemy.schema.MetaData()
            metadata.bind = engine

            volumes = sqlalchemy.Table('volumes', metadata, autoload=True)
            self.assertNotIn('encryption_key_id', volumes.c)

            snapshots = sqlalchemy.Table('snapshots', metadata, autoload=True)
            self.assertNotIn('encryption_key_id', snapshots.c)

            self.assertFalse(engine.dialect.has_table(engine.connect(),
                                                      'encryption'))

    def test_migration_018(self):
        """Test that added qos_specs table works correctly."""
        for (key, engine) in self.engines.items():
            migration_api.version_control(engine,
                                          TestMigrations.REPOSITORY,
                                          migration.db_initial_version())
            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 17)
            metadata = sqlalchemy.schema.MetaData()
            metadata.bind = engine

            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 18)
            self.assertTrue(engine.dialect.has_table(
                engine.connect(), "quality_of_service_specs"))
            qos_specs = sqlalchemy.Table('quality_of_service_specs',
                                         metadata,
                                         autoload=True)
            self.assertIsInstance(qos_specs.c.created_at.type,
                                  self.time_type[engine.name])
            self.assertIsInstance(qos_specs.c.updated_at.type,
                                  self.time_type[engine.name])
            self.assertIsInstance(qos_specs.c.deleted_at.type,
                                  self.time_type[engine.name])
            self.assertIsInstance(qos_specs.c.deleted.type,
                                  self.bool_type[engine.name])
            self.assertIsInstance(qos_specs.c.id.type,
                                  sqlalchemy.types.VARCHAR)
            self.assertIsInstance(qos_specs.c.specs_id.type,
                                  sqlalchemy.types.VARCHAR)
            self.assertIsInstance(qos_specs.c.key.type,
                                  sqlalchemy.types.VARCHAR)
            self.assertIsInstance(qos_specs.c.value.type,
                                  sqlalchemy.types.VARCHAR)

            migration_api.downgrade(engine, TestMigrations.REPOSITORY, 17)

            self.assertFalse(engine.dialect.has_table(
                engine.connect(), "quality_of_service_specs"))

    def test_migration_019(self):
        """Test that adding migration_status column works correctly."""
        for (key, engine) in self.engines.items():
            migration_api.version_control(engine,
                                          TestMigrations.REPOSITORY,
                                          migration.db_initial_version())
            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 18)
            metadata = sqlalchemy.schema.MetaData()
            metadata.bind = engine

            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 19)
            volumes = sqlalchemy.Table('volumes',
                                       metadata,
                                       autoload=True)
            self.assertIsInstance(volumes.c.migration_status.type,
                                  sqlalchemy.types.VARCHAR)

            migration_api.downgrade(engine, TestMigrations.REPOSITORY, 18)
            metadata = sqlalchemy.schema.MetaData()
            metadata.bind = engine

            volumes = sqlalchemy.Table('volumes',
                                       metadata,
                                       autoload=True)
            self.assertNotIn('migration_status', volumes.c)

    def test_migration_020(self):
        """Test adding volume_admin_metadata table works correctly."""
        for (key, engine) in self.engines.items():
            migration_api.version_control(engine,
                                          TestMigrations.REPOSITORY,
                                          migration.db_initial_version())
            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 19)
            metadata = sqlalchemy.schema.MetaData()
            metadata.bind = engine

            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 20)

            self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                     "volume_admin_metadata"))
            volume_admin_metadata = sqlalchemy.Table('volume_admin_metadata',
                                                     metadata,
                                                     autoload=True)

            self.assertIsInstance(volume_admin_metadata.c.created_at.type,
                                  self.time_type[engine.name])
            self.assertIsInstance(volume_admin_metadata.c.updated_at.type,
                                  self.time_type[engine.name])
            self.assertIsInstance(volume_admin_metadata.c.deleted_at.type,
                                  self.time_type[engine.name])
            self.assertIsInstance(volume_admin_metadata.c.deleted.type,
                                  self.bool_type[engine.name])
            self.assertIsInstance(volume_admin_metadata.c.id.type,
                                  sqlalchemy.types.INTEGER)
            self.assertIsInstance(volume_admin_metadata.c.volume_id.type,
                                  sqlalchemy.types.VARCHAR)
            self.assertIsInstance(volume_admin_metadata.c.key.type,
                                  sqlalchemy.types.VARCHAR)
            self.assertIsInstance(volume_admin_metadata.c.value.type,
                                  sqlalchemy.types.VARCHAR)

            migration_api.downgrade(engine, TestMigrations.REPOSITORY, 19)

            self.assertFalse(engine.dialect.has_table(engine.connect(),
                                                      "volume_admin_metadata"))

    def test_migration_021(self):
        """Test adding default data for quota classes works correctly."""
        for (key, engine) in self.engines.items():
            migration_api.version_control(engine,
                                          TestMigrations.REPOSITORY,
                                          migration.db_initial_version())
            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 20)
            metadata = sqlalchemy.schema.MetaData()
            metadata.bind = engine

            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 21)

            quota_class_metadata = sqlalchemy.Table('quota_classes',
                                                    metadata,
                                                    autoload=True)

            num_defaults = quota_class_metadata.count().\
                where(quota_class_metadata.c.class_name == 'default').\
                execute().scalar()

            self.assertEqual(3, num_defaults)

            migration_api.downgrade(engine, TestMigrations.REPOSITORY, 20)

            # Defaults should not be deleted during downgrade
            num_defaults = quota_class_metadata.count().\
                where(quota_class_metadata.c.class_name == 'default').\
                execute().scalar()

            self.assertEqual(3, num_defaults)

    def test_migration_022(self):
        """Test that adding disabled_reason column works correctly."""
        for (key, engine) in self.engines.items():
            migration_api.version_control(engine,
                                          TestMigrations.REPOSITORY,
                                          migration.db_initial_version())
            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 21)
            metadata = sqlalchemy.schema.MetaData()
            metadata.bind = engine

            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 22)
            services = sqlalchemy.Table('services',
                                        metadata,
                                        autoload=True)
            self.assertIsInstance(services.c.disabled_reason.type,
                                  sqlalchemy.types.VARCHAR)

            migration_api.downgrade(engine, TestMigrations.REPOSITORY, 21)
            metadata = sqlalchemy.schema.MetaData()
            metadata.bind = engine

            services = sqlalchemy.Table('services',
                                        metadata,
                                        autoload=True)
            self.assertNotIn('disabled_reason', services.c)
